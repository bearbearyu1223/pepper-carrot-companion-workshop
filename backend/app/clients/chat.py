"""Chat client interface and implementations.

Used by the chat orchestration layer to stream responses.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import aiofiles
import anthropic
import httpx
from anthropic.types import (
    Base64ImageSourceParam,
    CacheControlEphemeralParam,
    ImageBlockParam,
    MessageParam,
    TextBlockParam,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ContentBlockText(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ContentBlockImage(BaseModel):
    type: Literal["image"] = "image"
    url: str  # storage-resolved URL


ContentBlock = ContentBlockText | ContentBlockImage


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]


class ChatClient(Protocol):
    # Implementations are `async def stream(...) -> AsyncIterator[str]: yield ...`,
    # i.e. async-generator functions. Calling one returns the generator directly,
    # so the Protocol declares a sync function returning AsyncIterator — that's
    # what `async for token in client.stream(...)` actually consumes.
    def stream(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Stream text tokens for the next assistant turn."""
        ...

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int = 256,
        json_format: bool | dict[str, Any] = False,
    ) -> str:
        """One-shot completion. Returns the full assistant text in one call.

        Used for short side-channel calls (suggestion generation, classifiers)
        where streaming buys nothing.

        `json_format` controls structured output:
          - False: no constraint.
          - True: bare JSON (Ollama's `format: "json"` — keeps it JSON-shaped
            but doesn't enforce a schema; small models drift).
          - dict (a JSON Schema): constrains the output to match the schema.
            Strongly recommended over True for any caller that depends on the
            shape — Ollama's structured-output mode enforces the schema during
            sampling so the response will always match.
        """
        ...


# ─────────────────────────────────────────────────────────────────────────────


class OllamaChatClient:
    """Local chat via Ollama's `/api/chat` streaming endpoint.

    Supports multimodal input: each `ContentBlockImage.url` is resolved to
    base64 image bytes (http(s) → fetched, file:// or raw path → read locally)
    and attached to the corresponding message via Ollama's per-message
    `images` array.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._headers = dict(headers) if headers else {}

    @staticmethod
    async def _image_url_to_b64(url: str, http: httpx.AsyncClient) -> str:
        if url.startswith(("http://", "https://")):
            response = await http.get(url)
            response.raise_for_status()
            data = response.content
        else:
            path = Path(url[len("file://"):]) if url.startswith("file://") else Path(url)
            async with aiofiles.open(path, "rb") as f:
                data = await f.read()
        return base64.b64encode(data).decode("ascii")

    @classmethod
    async def _to_ollama_messages(
        cls, messages: list[Message], http: httpx.AsyncClient
    ) -> list[dict[str, Any]]:
        ollama_messages: list[dict[str, Any]] = []
        for msg in messages:
            text_parts: list[str] = []
            images_b64: list[str] = []
            for block in msg.content:
                if isinstance(block, ContentBlockText):
                    text_parts.append(block.text)
                elif isinstance(block, ContentBlockImage):
                    images_b64.append(await cls._image_url_to_b64(block.url, http))
            entry: dict[str, Any] = {
                "role": msg.role,
                "content": "\n".join(text_parts),
            }
            if images_b64:
                entry["images"] = images_b64
            ollama_messages.append(entry)
        return ollama_messages

    async def stream(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        # 180s covers vision-multimodal generation, which can stall for 30-60s
        # before the first token on a cold model.
        timeout = httpx.Timeout(180.0)
        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as client:
            ollama_messages = await self._to_ollama_messages(messages, client)
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": ollama_messages,
                "stream": True,
                "options": {"num_predict": max_tokens},
            }
            if system:
                payload["system"] = system
            async with client.stream(
                "POST", f"{self._base_url}/api/chat", json=payload
            ) as response:
                if response.status_code // 100 != 2:
                    body = (await response.aread()).decode("utf-8", errors="replace")[:500]
                    raise RuntimeError(
                        f"Ollama /api/chat returned {response.status_code}: {body}"
                    )
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("OllamaChatClient: skipped non-JSON line: %r", line[:200])
                        continue
                    msg = chunk.get("message")
                    if isinstance(msg, dict):
                        token = msg.get("content")
                        if isinstance(token, str) and token:
                            yield token
                    if chunk.get("done") is True:
                        return

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int = 256,
        json_format: bool | dict[str, Any] = False,
    ) -> str:
        timeout = httpx.Timeout(60.0)
        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as client:
            ollama_messages = await self._to_ollama_messages(messages, client)
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": ollama_messages,
                "stream": False,
                "options": {"num_predict": max_tokens},
            }
            if system:
                payload["system"] = system
            if json_format:
                # Ollama's structured-output knob. A dict is a JSON schema and
                # is enforced during sampling — strongly preferred. The bare
                # string "json" only forces JSON-shaped output without schema,
                # which small models freely ignore (they emit valid JSON with
                # invented keys).
                payload["format"] = json_format if isinstance(json_format, dict) else "json"
            response = await client.post(f"{self._base_url}/api/chat", json=payload)
            if response.status_code // 100 != 2:
                body = response.text[:500]
                raise RuntimeError(
                    f"Ollama /api/chat returned {response.status_code}: {body}"
                )
            data = response.json()
            msg = data.get("message") or {}
            content = msg.get("content")
            return content if isinstance(content, str) else ""


# ─────────────────────────────────────────────────────────────────────────────


_SUPPORTED_IMAGE_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)


def _guess_image_media_type(
    url: str,
) -> Literal["image/jpeg", "image/png", "image/gif", "image/webp"]:
    """Guess one of Anthropic's four supported image media types from a URL."""
    # Strip query string before extension lookup — `foo.png?v=1` would otherwise miss.
    clean = url.split("?", 1)[0]
    guess = mimetypes.guess_type(clean)[0] or ""
    if guess in _SUPPORTED_IMAGE_TYPES:
        # cast back to the Literal — guess_type returns plain str.
        return cast(
            Literal["image/jpeg", "image/png", "image/gif", "image/webp"], guess
        )
    return "image/png"


class AnthropicChatClient:
    """Cloud chat via Anthropic Messages API.

    Multimodal input: image URLs in `ContentBlockImage` are fetched and base64-
    encoded before being sent to Anthropic. We don't use Anthropic's URL image
    source because local-storage URLs (`http://localhost:8000/images/...`)
    aren't reachable from Anthropic's servers; base64 keeps the code path
    uniform whether the storage backend is local or R2.

    Prompt caching: top-level `cache_control={"type": "ephemeral"}` auto-caches
    the last cacheable block on each request. Across multi-turn chat that means
    each turn's full prior prefix (system prompt + page-context + earlier
    messages) is cached for the next turn — typically ~90% read discount on
    tokens that repeat across turns.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def aclose(self) -> None:
        await self._client.close()

    @classmethod
    async def _image_url_to_b64_source(
        cls, url: str, http: httpx.AsyncClient
    ) -> Base64ImageSourceParam:
        if url.startswith(("http://", "https://")):
            response = await http.get(url)
            response.raise_for_status()
            data = response.content
            # Prefer the server's content-type if it's a supported image type;
            # fall back to URL-extension guess otherwise.
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if content_type in _SUPPORTED_IMAGE_TYPES:
                media_type = cast(
                    Literal["image/jpeg", "image/png", "image/gif", "image/webp"],
                    content_type,
                )
            else:
                media_type = _guess_image_media_type(url)
        else:
            path = Path(url[len("file://"):]) if url.startswith("file://") else Path(url)
            async with aiofiles.open(path, "rb") as f:
                data = await f.read()
            media_type = _guess_image_media_type(url)
        return Base64ImageSourceParam(
            type="base64",
            media_type=media_type,
            data=base64.b64encode(data).decode("ascii"),
        )

    @classmethod
    async def _to_anthropic_messages(
        cls, messages: list[Message], http: httpx.AsyncClient
    ) -> list[MessageParam]:
        result: list[MessageParam] = []
        for msg in messages:
            content_blocks: list[TextBlockParam | ImageBlockParam] = []
            for block in msg.content:
                if isinstance(block, ContentBlockText):
                    content_blocks.append(TextBlockParam(type="text", text=block.text))
                elif isinstance(block, ContentBlockImage):
                    source = await cls._image_url_to_b64_source(block.url, http)
                    content_blocks.append(ImageBlockParam(type="image", source=source))
            result.append({"role": msg.role, "content": content_blocks})
        return result

    async def stream(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        # Image fetches are sequential and finish before the Anthropic stream
        # opens — keeps the streaming connection short-lived (only the model
        # output time, not image-download time).
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as http:
            anthropic_messages = await self._to_anthropic_messages(messages, http)

        cache_control: CacheControlEphemeralParam = {"type": "ephemeral"}
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=anthropic_messages,
            cache_control=cache_control,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int = 256,
        json_format: bool | dict[str, Any] = False,
    ) -> str:
        del json_format  # Claude follows JSON formatting from the prompt reliably.
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as http:
            anthropic_messages = await self._to_anthropic_messages(messages, http)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=anthropic_messages,
        )
        return "".join(
            block.text for block in response.content if block.type == "text"
        )
