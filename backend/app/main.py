"""FastAPI application entrypoint.

Minimal version for the workshop-stage starter (Posts 2 + 3). Exposes a
`/health` endpoint and — when STORAGE_BACKEND=local — mounts the
LocalStorage root at the URL prefix that `LocalStorage.url_for()`
advertises, so images written through the Storage Protocol can be
fetched by the browser.

The full project mounts five API routers, a chat orchestrator, and a
retrieval service on top of this scaffold; they land in later posts and
live in a different repository.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    force=True,
)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Pepper&Carrot Reading Companion — Workshop Starter",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
