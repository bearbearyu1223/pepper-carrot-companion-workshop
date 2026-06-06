"""FastAPI application entrypoint.

Wires up middleware, mounts the API routers, builds the chat orchestrator on
startup, and handles startup/shutdown of the SQLAlchemy async engine.

Post 6 adds the chat pipeline: a `ChatOrchestrator` (retrieval + prompt +
model call) is built once in `lifespan` and shared across requests via
`app.state`. The world-graph routes and cloud deploy land in later posts and
live in the full project repository.
"""

from __future__ import annotations

import asyncio
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

from app.api import episodes, messages, retrieve, sessions, world_graph  # noqa: E402
from app.clients import get_chat_client, get_embedding_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.session import close_engine, init_engine  # noqa: E402
from app.orchestration.chat import ChatOrchestrator  # noqa: E402
from app.retrieval.service import CollectionNotReadyError, RetrievalService  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the DB engine on startup; build the chat stack in the background.

    uvicorn binds the listening socket only *after* this startup phase returns,
    so anything slow here delays the bind. Constructing `RetrievalService` opens
    the baked Chroma index synchronously, and on a small VM that load is slow
    enough that Fly's deploy-time listen check fires before the socket is up
    ("not listening on the expected address"). So we do only the cheap work
    (engine init) inline and build the Chroma-backed orchestrator in a background
    task: `/health` and `/api/episodes` serve immediately, and the chat route
    returns a 503 for the brief window until the orchestrator is ready.
    """
    settings = get_settings()
    init_engine(settings.database_url)
    app.state.chat_orchestrator = None
    app.state.retrieval_service = None

    async def _build_chat_stack() -> None:
        # `RetrievalService` holds a Chroma client; the embedding model loads
        # lazily on first query. If no episode has been ingested yet, `pages_v1`
        # doesn't exist — degrade gracefully so the episodes API still serves and
        # the chat endpoint returns a clear 503. The constructor opens the index
        # synchronously, so run it off the event loop to keep `/health`
        # responsive while it loads.
        try:
            retrieval = await asyncio.to_thread(
                RetrievalService,
                settings.chroma_persist_dir,
                get_embedding_client(settings),
            )
            # Shared by the chat orchestrator and the /api/retrieve route, so the
            # latter doesn't reach into orchestrator privates.
            app.state.retrieval_service = retrieval
            app.state.chat_orchestrator = ChatOrchestrator(
                get_chat_client(settings), retrieval
            )
            logger.info("Chat orchestrator ready (page-mode retrieval).")
        except CollectionNotReadyError as exc:
            logger.warning("Chat disabled — %s", exc)
        except Exception:  # never let a startup failure crash the whole app
            logger.exception("Failed to build the chat orchestrator.")

    build_task = asyncio.create_task(_build_chat_stack())
    try:
        yield
    finally:
        build_task.cancel()
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

    # API routes. Episodes (Post 5) + sessions and chat messages (Post 6) +
    # world graph (Post 9) + retrieval inspection (the MCP/eval surface — see
    # docs/decisions/0006-retrieval-endpoint.md). The sessions and messages
    # routers share the /api/sessions prefix so the message path resolves to
    # /api/sessions/{id}/messages.
    app.include_router(episodes.router, prefix="/api/episodes", tags=["episodes"])
    app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
    app.include_router(messages.router, prefix="/api/sessions", tags=["chat"])
    app.include_router(retrieve.router, prefix="/api/retrieve", tags=["retrieve"])
    app.include_router(
        world_graph.router, prefix="/api/world-graph", tags=["world-graph"]
    )

    # Local image serving. Mount path is derived from `local_image_url_prefix`
    # so the backend serves files at exactly the URL that
    # `LocalStorage.url_for()` advertises. See Post 3 ("Seam 1 — Storage").
    if settings.storage_backend == "local":
        mount_path = urlparse(settings.local_image_url_prefix).path or "/images"
        settings.local_image_dir.mkdir(parents=True, exist_ok=True)

        # World-graph art lives OUTSIDE local_image_dir, at data/world-graph/
        # images/ (alongside the YAML the loader consumes — see Post 9). The
        # `image_url` keys stored on world_entities use a `world-graph/...`
        # prefix, so we mount the corresponding directory at the same
        # sub-path. Registered BEFORE the parent /images mount so FastAPI
        # tries the inner mount first on overlapping paths — without that,
        # the parent mount swallows /images/world-graph/images/* and 404s
        # because data/images/world-graph/images/ doesn't exist.
        world_graph_images_dir = (
            settings.local_image_dir.parent / "world-graph" / "images"
        )
        if world_graph_images_dir.is_dir():
            app.mount(
                f"{mount_path}/world-graph/images",
                StaticFiles(directory=world_graph_images_dir),
                name="world-graph-images",
            )

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
