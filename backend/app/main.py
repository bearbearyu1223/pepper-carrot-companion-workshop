"""FastAPI application entrypoint.

Wires up middleware, mounts the episodes router, and handles startup/shutdown
of the SQLAlchemy async engine.

This is the Post 5 state of the workshop starter: episodes list + detail,
plus the local-images static-files mount from Post 3. The chat orchestrator,
retrieval service, sessions, and world-graph routes land in later posts and
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

from app.api import episodes  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.session import close_engine, init_engine  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the async DB engine on startup, dispose it on shutdown."""
    del app  # not used in this stage of the build
    settings = get_settings()
    init_engine(settings.database_url)
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

    # API routes (Post 5).
    app.include_router(episodes.router, prefix="/api/episodes", tags=["episodes"])

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
