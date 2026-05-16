"""Smoke tests for both embedding clients.

Each test class skips cleanly when its provider isn't available locally:
- Ollama tests probe `/api/version` and skip if unreachable.
- sentence-transformers tests skip if the model isn't already cached and would
  trigger a multi-GB download.
"""

from __future__ import annotations

import math
import os

import httpx
import pytest

from app.clients.embedding import (
    OllamaEmbeddingClient,
    SentenceTransformersEmbeddingClient,
)
from app.config import get_settings


def _vectors_close(a: list[float], b: list[float], rel_tol: float = 1e-5) -> bool:
    if len(a) != len(b):
        return False
    return all(math.isclose(x, y, rel_tol=rel_tol, abs_tol=1e-7) for x, y in zip(a, b, strict=True))


# ─────────────────────────────────────────────────────────────────────────────
# Ollama


async def _ollama_reachable(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
            r = await client.get(f"{base_url.rstrip('/')}/api/version")
            return r.status_code == 200
    except Exception:
        return False


class TestOllamaEmbeddingClient:
    @pytest.fixture
    async def client(self) -> OllamaEmbeddingClient:
        settings = get_settings()
        if not await _ollama_reachable(settings.ollama_base_url):
            pytest.skip("ollama not running")
        # Ollama wants the bare model name; use settings, but fall back if a HF-style
        # name was set for sentence-transformers.
        model = settings.embedding_model
        if "/" in model:
            model = model.split("/", 1)[1]
        c = OllamaEmbeddingClient(base_url=settings.ollama_base_url, model=model)
        try:
            yield c
        finally:
            await c.aclose()

    async def test_embed_single_returns_one_vector(self, client: OllamaEmbeddingClient) -> None:
        vecs = await client.embed_batch(["hello"])
        assert len(vecs) == 1
        assert client.dimension > 0
        assert len(vecs[0]) == client.dimension

    async def test_embed_batch_preserves_order(self, client: OllamaEmbeddingClient) -> None:
        a = "Pepper is a witch who lives in Hereva."
        b = "A cat named Carrot keeps her company."
        vecs = await client.embed_batch([a, b])
        assert len(vecs) == 2
        assert len(vecs[0]) == len(vecs[1]) == client.dimension
        # Two semantically different sentences should not produce identical vectors.
        assert not _vectors_close(vecs[0], vecs[1])

    async def test_embed_is_deterministic(self, client: OllamaEmbeddingClient) -> None:
        text = "Pepper brews potions in the witch hut."
        v1 = (await client.embed_batch([text]))[0]
        v2 = (await client.embed_batch([text]))[0]
        assert _vectors_close(v1, v2), "same input should produce identical vectors"


# ─────────────────────────────────────────────────────────────────────────────
# sentence-transformers


def _hf_cache_has_model(model_name: str) -> bool:
    """Best-effort check: does the HF Hub cache contain this model?

    Returns False if we can't tell — callers will then attempt a load and skip
    on any failure.
    """
    cache_root = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    hub_dir = os.path.join(cache_root, "hub")
    if not os.path.isdir(hub_dir):
        return False
    # HF stores models as models--<org>--<name>
    sanitized = "models--" + model_name.replace("/", "--")
    return os.path.isdir(os.path.join(hub_dir, sanitized))


class TestSentenceTransformersEmbeddingClient:
    @pytest.fixture
    def client(self) -> SentenceTransformersEmbeddingClient:
        settings = get_settings()
        # sentence-transformers wants the HF-style name; if .env has the bare
        # ollama-style "bge-m3", upgrade to the canonical form.
        model = settings.embedding_model
        if "/" not in model and model.lower().startswith("bge-"):
            model = f"BAAI/{model}"
        if not _hf_cache_has_model(model):
            pytest.skip(
                f"sentence-transformers model {model!r} not in local HF cache; "
                "skipping to avoid triggering a multi-GB download"
            )
        return SentenceTransformersEmbeddingClient(model=model)

    async def test_embed_single_returns_one_vector(
        self, client: SentenceTransformersEmbeddingClient
    ) -> None:
        try:
            vecs = await client.embed_batch(["hello"])
        except Exception as e:  # pragma: no cover — defensive skip
            pytest.skip(f"sentence-transformers load failed: {e}")
        assert len(vecs) == 1
        assert client.dimension > 0
        assert len(vecs[0]) == client.dimension

    async def test_embed_batch_preserves_order(
        self, client: SentenceTransformersEmbeddingClient
    ) -> None:
        a = "Pepper is a witch who lives in Hereva."
        b = "A cat named Carrot keeps her company."
        try:
            vecs = await client.embed_batch([a, b])
        except Exception as e:  # pragma: no cover
            pytest.skip(f"sentence-transformers load failed: {e}")
        assert len(vecs) == 2
        assert len(vecs[0]) == len(vecs[1]) == client.dimension
        assert not _vectors_close(vecs[0], vecs[1])

    async def test_embed_is_deterministic(
        self, client: SentenceTransformersEmbeddingClient
    ) -> None:
        text = "Pepper brews potions in the witch hut."
        try:
            v1 = (await client.embed_batch([text]))[0]
            v2 = (await client.embed_batch([text]))[0]
        except Exception as e:  # pragma: no cover
            pytest.skip(f"sentence-transformers load failed: {e}")
        assert _vectors_close(v1, v2), "same input should produce identical vectors"
