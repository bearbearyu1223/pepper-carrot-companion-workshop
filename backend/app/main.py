"""FastAPI application entrypoint.

Wires up middleware, mounts the API routers, builds the chat orchestrator on
startup, and handles startup/shutdown of the SQLAlchemy async engine.

Post 6 adds the chat pipeline: a `ChatOrchestrator` (retrieval + prompt +
model call) is built once in `lifespan` and shared across requests via
`app.state`. The world-graph routes and cloud deploy land in later posts and
live in the full project repository.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)

from app.api import episodes, messages, sessions  # noqa: E402
from app.clients import get_chat_client, get_embedding_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.session import close_engine, init_engine  # noqa: E402
from app.orchestration.chat import ChatOrchestrator  # noqa: E402
from app.retrieval.service import CollectionNotReadyError, RetrievalService  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the DB engine and chat orchestrator on startup; dispose on shutdown."""
    settings = get_settings()
    init_engine(settings.database_url)

    # Build the chat stack once. `RetrievalService` holds a Chroma client; the
    # embedding model loads lazily on first query. If no episode has been
    # ingested yet, `pages_v1` doesn't exist — degrade gracefully so the
    # episodes API still serves, and the chat endpoint returns a clear 503.
    try:
        retrieval = RetrievalService(
            settings.chroma_persist_dir, get_embedding_client(settings)
        )
        app.state.chat_orchestrator = ChatOrchestrator(
            get_chat_client(settings), retrieval
        )
        logger.info("Chat orchestrator ready (page-mode retrieval).")
    except CollectionNotReadyError as exc:
        app.state.chat_orchestrator = None
        logger.warning("Chat disabled — %s", exc)

    yield
    await close_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Pepper&Carrot Reading Companion — Workshop Starter",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes. Episodes (Post 5) + sessions and chat messages (Post 6).
    # The sessions and messages routers share the /api/sessions prefix so the
    # message path resolves to /api/sessions/{id}/messages.
    app.include_router(episodes.router, prefix="/api/episodes", tags=["episodes"])
    app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
    app.include_router(messages.router, prefix="/api/sessions", tags=["chat"])

    # Local image serving. Mount path is derived from `local_image_url_prefix`
    # so the backend serves files at exactly the URL that
    # `LocalStorage.url_for()` advertises. See Post 3 ("Seam 1 — Storage").
    if settings.storage_backend == "local":
        mount_path = urlparse(settings.local_image_url_prefix).path or "/images"
        settings.local_image_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            mount_path,
            StaticFiles(directory=settings.local_image_dir),
            name="images",
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
