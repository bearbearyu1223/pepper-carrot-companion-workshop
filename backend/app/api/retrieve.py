"""Retrieval-inspection route — `POST /api/retrieve`.

Surfaces the *same* retrieval path the chat pipeline uses
(`RetrievalService.retrieve` + `fetch_chunk_text`) with scores + metadata +
canonical text, so an external MCP server / evaluator can measure retrieval
quality directly. The chat pipeline only ever leaks bare Chroma ids (in the
`done` SSE event); this route exposes the full ranked result.

It introduces **no new retrieval logic**: same Voyage embedding, same
lexicographic `$or` spoiler filter, same Postgres text lookup. The one
deliberate difference from the chat path is that the reader position arrives as
**request params** (validated) instead of from a `chat_sessions` row — which
makes the endpoint stateless and lets the boundary be probed deterministically.
The retrieval *logic* is identical; only the *source* of the boundary integers
differs. See docs/decisions/0006-retrieval-endpoint.md.

    curl -s -X POST localhost:8000/api/retrieve -H 'content-type: application/json' \\
      -d '{"mode":"page","query":"who is on this page?","current_episode":2,"current_page":3}'
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ratelimit import SlidingWindowRateLimiter, client_ip
from app.config import get_settings
from app.db.session import get_session
from app.retrieval.service import Mode, RetrievalService, fetch_chunk_text

router = APIRouter()

# Matches the chat message cap — a retrieval query is a sentence or two; this
# bounds the embedding-token cost a single request can run up.
_MAX_QUERY_CHARS = 2000
_K_MIN = 1
_K_MAX = 20

# One limiter instance, shared across requests, sized from settings at startup.
_retrieve_limiter = SlidingWindowRateLimiter(
    max_requests=get_settings().retrieve_rate_limit_per_minute,
    window_seconds=60.0,
)


async def rate_limit_retrieve(request: Request) -> None:
    """Per-IP throttle on the embedding-bearing retrieval endpoint.

    Raises HTTP 429 (with ``Retry-After``) past the configured budget. A no-op
    when ``retrieve_rate_limit_per_minute`` is 0. Tests disable it per-app via
    ``app.dependency_overrides[rate_limit_retrieve] = lambda: None``.
    """
    _retrieve_limiter.check(client_ip(request))


class RetrieveBody(BaseModel):
    mode: Mode
    query: str = Field(min_length=1, max_length=_MAX_QUERY_CHARS)
    k: int = Field(default=5, ge=_K_MIN, le=_K_MAX)
    # Required only for page mode (validated in the handler so the failure is a
    # 400, not a pydantic 422). Wiki mode ignores them — universe facts aren't
    # spoiler-gated. ``ge=1`` keeps a supplied position to a real 1-based index.
    current_episode: int | None = Field(default=None, ge=1)
    current_page: int | None = Field(default=None, ge=1)


class Boundary(BaseModel):
    current_episode: int
    current_page: int


class RetrievedChunkOut(BaseModel):
    rank: int  # 1-based position in the ranked result
    chroma_id: str
    source_table: str  # "pages" | "wiki"
    source_id: str
    score: float  # 1 - cosine_distance
    metadata: dict[str, Any]
    text: str  # canonical Postgres text (markdown-stripped; "" if not found)


class RetrieveResponse(BaseModel):
    mode: Mode
    query: str
    boundary: Boundary | None  # the spoiler boundary in force; null for wiki
    chunks: list[RetrievedChunkOut]


def get_retrieval_service(request: Request) -> RetrievalService:
    """Return the `RetrievalService` built once in `lifespan` and stashed on
    `app.state`.

    It's `None` until the background chat-stack build finishes (and stays `None`
    when no episode has been ingested, so `pages_v1` doesn't exist). Mirrors the
    chat route's 503 behavior. Tests override this via
    `app.dependency_overrides[get_retrieval_service]`.
    """
    service = getattr(request.app.state, "retrieval_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Retrieval is unavailable — the index is still loading, or no "
                "episode has been ingested yet. Run the ingestion pipeline and "
                "restart the backend."
            ),
        )
    return cast(RetrievalService, service)


@router.post("", response_model=RetrieveResponse, dependencies=[Depends(rate_limit_retrieve)])
async def retrieve(
    body: RetrieveBody,
    db: Annotated[AsyncSession, Depends(get_session)],
    retrieval: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> RetrieveResponse:
    """POST /api/retrieve — ranked chunks with scores + metadata + text."""
    if body.mode == "page" and (
        body.current_episode is None or body.current_page is None
    ):
        raise HTTPException(
            status_code=400,
            detail="page mode requires current_episode and current_page",
        )

    chunks = await retrieval.retrieve(
        body.mode,
        body.query,
        # Ignored by wiki mode; for page mode the handler guaranteed both above.
        current_episode_number=body.current_episode or 0,
        current_page_number=body.current_page or 0,
    )
    texts = await fetch_chunk_text(db, chunks)

    items = [
        RetrievedChunkOut(
            rank=i + 1,
            chroma_id=chunk.chroma_id,
            source_table=chunk.source_table,
            source_id=chunk.source_id,
            score=chunk.score,
            metadata=chunk.metadata,
            text=text,
        )
        for i, (chunk, text) in enumerate(texts)
    ]

    boundary = (
        Boundary(current_episode=body.current_episode, current_page=body.current_page)
        if body.mode == "page"
        and body.current_episode is not None
        and body.current_page is not None
        else None
    )
    return RetrieveResponse(
        mode=body.mode, query=body.query, boundary=boundary, chunks=items
    )
