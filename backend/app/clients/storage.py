"""Storage client interface and implementations.

See docs/decisions/0003-storage-abstraction.md.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

import aiofiles


class Storage(Protocol):
    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Write bytes to the backing store at `key`. Idempotent (same key + content = no-op)."""
        ...

    async def url_for(self, key: str) -> str:
        """Resolve a relative key to a public URL the frontend can fetch."""
        ...

    async def exists(self, key: str) -> bool: ...


# ─────────────────────────────────────────────────────────────────────────────


class LocalStorage:
    """Filesystem-backed storage. Files are served by the FastAPI app via StaticFiles."""

    def __init__(self, root: Path, url_prefix: str) -> None:
        self._root = root
        self._url_prefix = url_prefix.rstrip("/")
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # Defensive: never let a key escape the root via "..".
        target = (self._root / key).resolve()
        if not str(target).startswith(str(self._root.resolve())):
            raise ValueError(f"Refusing to write outside storage root: {key}")
        return target

    _IDEMPOTENCY_COMPARE_LIMIT = 5 * 1024 * 1024  # bytes

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        path = self._path_for(key)
        if (
            len(content) <= self._IDEMPOTENCY_COMPARE_LIMIT
            and path.exists()
            and path.stat().st_size == len(content)
        ):
            async with aiofiles.open(path, "rb") as f:
                existing = await f.read()
            if existing == content:
                return
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)

    async def url_for(self, key: str) -> str:
        return f"{self._url_prefix}/{key}"

    async def exists(self, key: str) -> bool:
        path = self._path_for(key)
        return await asyncio.to_thread(path.exists)


# ─────────────────────────────────────────────────────────────────────────────


class R2Storage:
    """Cloudflare R2 (S3-compatible) storage. Production target."""

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_url_prefix: str,
    ) -> None:
        self._bucket = bucket
        self._public_url_prefix = public_url_prefix.rstrip("/")
        # TODO: initialize a boto3 S3 client pointing at the R2 endpoint:
        #   endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com"
        # Run blocking calls via asyncio.to_thread.

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Upload to R2 with public read + immutable cache headers.

        Headers to set:
        - Content-Type: <content_type>
        - Cache-Control: public, max-age=31536000, immutable
        """
        raise NotImplementedError

    async def url_for(self, key: str) -> str:
        return f"{self._public_url_prefix}/{key}"

    async def exists(self, key: str) -> bool:
        raise NotImplementedError
