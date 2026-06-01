"""Embedding client interface and implementations."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

import httpx

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingClient(Protocol):
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input text. Order preserved."""
        ...

    @property
    def dimension(self) -> int:
        """Embedding vector dimensionality. Used to validate against Chroma collections."""
        ...

    @property
    def model_name(self) -> str:
        """Identifier used as a tag on Chroma collections (e.g., 'bge-m3')."""
        ...


# ─────────────────────────────────────────────────────────────────────────────


class SentenceTransformersEmbeddingClient:
    """Local embeddings via sentence-transformers.

    Default and recommended for local-first development. BGE-M3 is the suggested model;
    multilingual, 1024-dim, fast on CPU and especially fast on MPS/CUDA.
    """

    def __init__(self, model: str) -> None:
        self._model_name = model
        self._model: SentenceTransformer | None = None
        self._dimension: int | None = None

    def _ensure_model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading sentence-transformers model %s (first use; may download ~2GB)", self._model_name)
            self._model = SentenceTransformer(self._model_name)
            # sentence-transformers renamed get_sentence_embedding_dimension to
            # get_embedding_dimension; prefer the new name and fall back for older versions.
            get_dim = getattr(self._model, "get_embedding_dimension", None)
            if get_dim is None:
                get_dim = self._model.get_sentence_embedding_dimension
            self._dimension = get_dim()
        return self._model

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._ensure_model()
        assert self._dimension is not None
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = await asyncio.to_thread(self._ensure_model)

        def _encode() -> list[list[float]]:
            arr = model.encode(
                texts,
                batch_size=32,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return [vec.tolist() for vec in arr]

        return await asyncio.to_thread(_encode)


# ─────────────────────────────────────────────────────────────────────────────


class OllamaEmbeddingClient:
    """Embeddings via Ollama. Convenient when you're already running Ollama for vision/chat."""

    def __init__(
        self,
        base_url: str,
        model: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        # 180s matches OllamaChatClient — needs to cover serverless-GPU cold
        # starts (Modal: ~30-75s for bge-m3 to load into VRAM after idle).
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0),
            headers=dict(headers) if headers else {},
        )
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            # Issue a synchronous probe via a fresh event loop only if we're not in one already.
            # Callers typically hit embed_batch first, but we guard here anyway.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None:
                raise RuntimeError(
                    "OllamaEmbeddingClient.dimension accessed before any embed_batch call "
                    "from inside a running event loop; call `await embed_batch([...])` first."
                )
            asyncio.run(self._probe_dimension())
        assert self._dimension is not None
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model

    async def _probe_dimension(self) -> None:
        vecs = await self._embed(["dim probe"])
        self._dimension = len(vecs[0])

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.post(
            f"{self._base_url}/api/embed",
            json={"model": self._model, "input": texts},
        )
        if response.status_code // 100 != 2:
            body = response.text[:500]
            raise RuntimeError(
                f"Ollama /api/embed returned {response.status_code}: {body}"
            )
        data = response.json()
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError(
                f"Ollama /api/embed returned unexpected payload: {str(data)[:500]}"
            )
        return [list(map(float, vec)) for vec in embeddings]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors = await self._embed(texts)
        if self._dimension is None and vectors:
            self._dimension = len(vectors[0])
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()


# ─────────────────────────────────────────────────────────────────────────────


class VoyageEmbeddingClient:
    """Embeddings via the Voyage AI HTTP API.

    Voyage is Anthropic's recommended embeddings partner — a hosted API with
    no infrastructure to manage, useful when the rest of the chat layer has
    moved off Modal-hosted Ollama (CHAT_PROVIDER=anthropic) and there's no
    local GPU to lean on for bge-m3.

    The wire format is a thin POST to /embeddings with `{"input": [...],
    "model": "voyage-4-lite"}` and `Authorization: Bearer <key>`. Response
    shape is `{"data": [{"embedding": [...], "index": N}, ...]}` with the
    indices guaranteed to mirror the input order — we still re-sort by
    `index` defensively so a future API change can't silently scramble
    vector → document alignment in the Chroma upsert.

    See https://docs.voyageai.com/reference/embeddings-api for the full
    schema, https://docs.voyageai.com/docs/embeddings for model options.
    """

    _DEFAULT_BASE_URL = "https://api.voyageai.com/v1"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        client_kwargs: dict[str, object] = {
            "base_url": (base_url or self._DEFAULT_BASE_URL).rstrip("/"),
            "timeout": httpx.Timeout(30.0),
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        }
        # `transport` is the standard httpx seam tests use to inject a fake
        # network. Production callers leave it unset; `tests/test_embedding.py`
        # passes `httpx.MockTransport(...)` to keep the suite offline.
        if transport is not None:
            client_kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**client_kwargs)  # type: ignore[arg-type]
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        # Same shape as OllamaEmbeddingClient: dimension is discovered on the
        # first successful embed call. Callers hit embed_batch first in
        # practice; we guard the cold-access case behind a clear error so
        # the test suite catches misuse instead of swallowing it.
        if self._dimension is None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._probe_dimension())
            else:
                raise RuntimeError(
                    "VoyageEmbeddingClient.dimension accessed before any "
                    "embed_batch call from inside a running event loop; "
                    "call `await embed_batch([...])` first."
                )
        assert self._dimension is not None
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model

    async def _probe_dimension(self) -> None:
        vecs = await self._embed(["dim probe"])
        self._dimension = len(vecs[0])

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.post(
            "/embeddings",
            json={"input": texts, "model": self._model},
        )
        if response.status_code // 100 != 2:
            body = response.text[:500]
            raise RuntimeError(
                f"Voyage /embeddings returned {response.status_code}: {body}"
            )
        data = response.json()
        rows = data.get("data")
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise RuntimeError(
                f"Voyage /embeddings returned unexpected payload: {str(data)[:500]}"
            )
        # Re-sort by `index` so the returned order matches the input order
        # even if Voyage ever stops guaranteeing it. The Chroma upsert in
        # ingestion/chroma_writer.py zips (id, vec) by position; a silent
        # reorder here would silently misalign every document.
        ordered = sorted(rows, key=lambda row: int(row.get("index", 0)))
        return [list(map(float, row["embedding"])) for row in ordered]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = await self._embed(texts)
        if self._dimension is None and vectors:
            self._dimension = len(vectors[0])
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()
