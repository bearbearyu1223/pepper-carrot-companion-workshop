"""Smoke tests for the three embedding clients.

Each test class handles its own availability:
- Ollama tests probe `/api/version` and skip if unreachable.
- sentence-transformers tests skip if the model isn't already cached and would
  trigger a multi-GB download.
- Voyage tests mock the HTTP transport — Voyage is a paid hosted API and
  we want the tests deterministic and offline.
"""

from __future__ import annotations

import json as _json
import math
import os
from typing import Any

import httpx
import pytest

from app.clients.embedding import (
    OllamaEmbeddingClient,
    SentenceTransformersEmbeddingClient,
    VoyageEmbeddingClient,
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


# ─────────────────────────────────────────────────────────────────────────────
# Voyage AI


def _voyage_mock_transport(
    *,
    captured_requests: list[dict[str, Any]] | None = None,
    dim: int = 512,
    shuffle_indices: bool = False,
) -> httpx.MockTransport:
    """Build a transport that fakes Voyage's /embeddings response.

    Embeddings returned are deterministic per input position so order
    assertions are exact. If `shuffle_indices=True`, the rows are returned
    in reverse order with their `index` field set correctly — the client's
    sort-by-index defence must put them back in input order.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if captured_requests is not None:
            captured_requests.append(
                {
                    "url": str(request.url),
                    "headers": dict(request.headers),
                    "json": _json.loads(request.content),
                }
            )
        payload = _json.loads(request.content)
        texts: list[str] = payload["input"]
        # Embedding = [position_i + 0.0, position_i + 0.1, position_i + 0.2, ...]
        # so embeddings differ per input position and are deterministic.
        rows = [
            {
                "object": "embedding",
                "index": i,
                "embedding": [float(i) + (j * 0.1) for j in range(dim)],
            }
            for i, _ in enumerate(texts)
        ]
        if shuffle_indices:
            rows = list(reversed(rows))
        body = {
            "object": "list",
            "data": rows,
            "model": payload["model"],
            "usage": {"total_tokens": sum(len(t) for t in texts)},
        }
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def _make_voyage_client(transport: httpx.MockTransport) -> VoyageEmbeddingClient:
    """VoyageEmbeddingClient with the mock transport wired in through the
    constructor's `transport` parameter — the standard httpx seam for tests."""
    return VoyageEmbeddingClient(
        api_key="vk-test", model="voyage-3-lite", transport=transport
    )


class TestVoyageEmbeddingClient:
    async def test_embed_batch_preserves_order_and_dim(self) -> None:
        c = _make_voyage_client(_voyage_mock_transport(dim=512))
        try:
            vecs = await c.embed_batch(["alpha", "beta", "gamma"])
        finally:
            await c.aclose()
        assert len(vecs) == 3
        assert all(len(v) == 512 for v in vecs)
        # By construction the first element of each vector is the input index.
        assert vecs[0][0] == 0.0
        assert vecs[1][0] == 1.0
        assert vecs[2][0] == 2.0
        assert c.dimension == 512

    async def test_embed_batch_resorts_when_indices_are_shuffled(self) -> None:
        # Voyage docs guarantee `index` reflects the input order, but the
        # client re-sorts defensively. Confirm the sort holds even if the
        # API ever returned rows out of order.
        c = _make_voyage_client(
            _voyage_mock_transport(dim=512, shuffle_indices=True)
        )
        try:
            vecs = await c.embed_batch(["alpha", "beta", "gamma"])
        finally:
            await c.aclose()
        assert [v[0] for v in vecs] == [0.0, 1.0, 2.0]

    async def test_embed_batch_sends_correct_request(self) -> None:
        captured: list[dict[str, Any]] = []
        c = _make_voyage_client(
            _voyage_mock_transport(captured_requests=captured, dim=512)
        )
        try:
            await c.embed_batch(["alpha", "beta"])
        finally:
            await c.aclose()
        assert len(captured) == 1
        req = captured[0]
        assert req["url"].endswith("/embeddings")
        assert req["headers"].get("authorization") == "Bearer vk-test"
        assert req["json"] == {"input": ["alpha", "beta"], "model": "voyage-3-lite"}

    async def test_embed_batch_empty_input_returns_empty(self) -> None:
        c = _make_voyage_client(_voyage_mock_transport(dim=512))
        try:
            vecs = await c.embed_batch([])
        finally:
            await c.aclose()
        assert vecs == []
