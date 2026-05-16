"""Async SQLAlchemy session management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _extract_ssl_connect_args(database_url: str) -> tuple[str, dict[str, Any]]:
    """Pop `ssl` / `sslmode` query params off the URL into asyncpg-shaped connect_args.

    SQLAlchemy's asyncpg dialect forwards unknown URL query params as kwargs to
    asyncpg's `connect()`, which accepts `ssl=` but NOT `sslmode=`. Likewise it
    rejects `ssl=true` because the value passes through unchanged. So we strip
    these params from the URL and translate them into a `connect_args` dict
    that asyncpg accepts directly.
    """
    parts = urlsplit(database_url)
    if not parts.query:
        return database_url, {}

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    keep: list[tuple[str, str]] = []
    connect_args: dict[str, Any] = {}
    for key, value in pairs:
        if key in ("ssl", "sslmode"):
            if value.lower() in ("true", "1"):
                connect_args["ssl"] = "require"
            elif value.lower() in ("false", "0"):
                connect_args["ssl"] = False
            else:
                # Pass libpq-style values straight through; asyncpg understands
                # disable / allow / prefer / require / verify-ca / verify-full.
                connect_args["ssl"] = value
        else:
            keep.append((key, value))

    cleaned = urlunsplit(parts._replace(query=urlencode(keep)))
    return cleaned, connect_args


def init_engine(database_url: str) -> None:
    """Initialize the async engine and session factory. Call once on app startup."""
    global _engine, _session_factory
    cleaned_url, connect_args = _extract_ssl_connect_args(database_url)
    _engine = create_async_engine(
        cleaned_url,
        pool_pre_ping=True,
        echo=False,
        connect_args=connect_args,
    )
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def close_engine() -> None:
    """Dispose the engine on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency for an async session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_engine() first.")
    async with _session_factory() as session:
        yield session
