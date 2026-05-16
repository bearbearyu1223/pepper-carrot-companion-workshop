"""Provider-agnostic client interfaces.

This package is the **only** place that imports model and storage SDKs directly.
All other code receives Protocol-typed clients from the factory functions below.

See docs/decisions/0002-model-provider-abstraction.md for the rationale.
"""

from __future__ import annotations

from app.clients.chat import (
    AnthropicChatClient,
    ChatClient,
    OllamaChatClient,
)
from app.clients.embedding import (
    EmbeddingClient,
    OllamaEmbeddingClient,
    SentenceTransformersEmbeddingClient,
)
from app.clients.storage import LocalStorage, R2Storage, Storage
from app.clients.vision import JsonFileVisionClient, VisionClient
from app.config import Settings


def get_vision_client(settings: Settings) -> VisionClient:
    # Single implementation: each page image must have a sibling .json file
    # containing a serialised PageDescription. The `ingest-from-images`
    # Claude Code skill produces those JSON files.
    del settings  # no settings consumed today; kept for future provider opts
    return JsonFileVisionClient()


def _modal_proxy_headers(settings: Settings) -> dict[str, str]:
    """Modal proxy-auth headers when both tokens are set; empty otherwise.

    Setting only one of the two is a config error — fail loudly so the
    operator notices before requests start 401-ing in production.
    """
    if settings.modal_proxy_token_id and settings.modal_proxy_token_secret:
        return {
            "Modal-Key": settings.modal_proxy_token_id,
            "Modal-Secret": settings.modal_proxy_token_secret,
        }
    if settings.modal_proxy_token_id or settings.modal_proxy_token_secret:
        raise RuntimeError(
            "Modal proxy auth requires BOTH modal_proxy_token_id and "
            "modal_proxy_token_secret to be set."
        )
    return {}


def get_chat_client(settings: Settings) -> ChatClient:
    if settings.chat_provider == "ollama":
        return OllamaChatClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_chat_model,
            headers=_modal_proxy_headers(settings),
        )
    if settings.chat_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when chat_provider=anthropic")
        return AnthropicChatClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    raise ValueError(f"Unknown chat_provider: {settings.chat_provider}")


def get_embedding_client(settings: Settings) -> EmbeddingClient:
    if settings.embedding_provider == "sentence-transformers":
        return SentenceTransformersEmbeddingClient(model=settings.embedding_model)
    if settings.embedding_provider == "ollama":
        return OllamaEmbeddingClient(
            base_url=settings.ollama_base_url,
            model=settings.embedding_model,
            headers=_modal_proxy_headers(settings),
        )
    raise ValueError(f"Unknown embedding_provider: {settings.embedding_provider}")


def get_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "local":
        return LocalStorage(
            root=settings.local_image_dir,
            url_prefix=settings.local_image_url_prefix,
        )
    if settings.storage_backend == "r2":
        for required in ("r2_account_id", "r2_access_key_id", "r2_secret_access_key", "r2_bucket"):
            if getattr(settings, required) is None:
                raise RuntimeError(f"{required.upper()} is required when storage_backend=r2")
        return R2Storage(
            account_id=settings.r2_account_id,  # type: ignore[arg-type]
            access_key_id=settings.r2_access_key_id,  # type: ignore[arg-type]
            secret_access_key=settings.r2_secret_access_key,  # type: ignore[arg-type]
            bucket=settings.r2_bucket,  # type: ignore[arg-type]
            public_url_prefix=settings.r2_public_url_prefix or "",
        )
    raise ValueError(f"Unknown storage_backend: {settings.storage_backend}")


__all__ = [
    "ChatClient",
    "EmbeddingClient",
    "Storage",
    "VisionClient",
    "get_chat_client",
    "get_embedding_client",
    "get_storage",
    "get_vision_client",
]
