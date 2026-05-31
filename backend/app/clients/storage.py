"""Storage client interface and implementations.

See docs/decisions/0003-storage-abstraction.md (the abstraction) and
docs/decisions/0004-cloud-deployment.md (why R2 is the production target).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

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
    """Cloudflare R2 (S3-compatible) storage. Production target — see Post 10.

    R2 speaks the S3 API, so the implementation is a thin async wrapper around
    a synchronous boto3 client routed at Cloudflare's R2 endpoint. The
    synchronous calls run in a worker thread via `asyncio.to_thread` so the
    FastAPI event loop never blocks on a network round-trip.

    At runtime, the backend's read path only ever touches `url_for()` — the
    image bytes have already been uploaded by `rclone` during deploy (see
    `docs/deployment.md`), and the URL is composed at API-response time. The
    `put()` and `exists()` methods exist for ingestion jobs that may someday
    run remotely; until then they're exercised only by tests.
    """

    # Public-read R2 buckets serve every object with these cache headers, so the
    # browser caches them aggressively after the first hit. Comic pages never
    # change once authored; if they do, the ingestion pipeline writes to a new
    # key (e.g. a fresh hash) rather than mutating an existing one.
    _CACHE_CONTROL = "public, max-age=31536000, immutable"

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
        # boto3 is imported lazily so the workshop's local-only path doesn't
        # need it installed. The factory in `clients/__init__.py` validates
        # that all four R2_* env vars are set before reaching this constructor.
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover — covered by missing-dep CI
            raise RuntimeError(
                "boto3 is required for STORAGE_BACKEND=r2. "
                "Install with `uv sync` — boto3 is pinned in pyproject.toml."
            ) from exc

        # Cloudflare's R2 endpoint is `<account_id>.r2.cloudflarestorage.com`;
        # the region is irrelevant (R2 is region-agnostic) but boto3 requires
        # *something*, so we pass `auto` per Cloudflare's docs.
        # https://developers.cloudflare.com/r2/api/s3/api/
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        """Upload to R2 with the immutable cache header.

        boto3 is synchronous — wrap in `asyncio.to_thread` so the event loop
        keeps serving other requests during the network round-trip.
        """

        def _put() -> None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                CacheControl=self._CACHE_CONTROL,
            )

        await asyncio.to_thread(_put)

    async def url_for(self, key: str) -> str:
        # The runtime hot path. No I/O — just a string compose. The bucket's
        # R2.dev or custom-domain prefix is configured per environment (see
        # `R2_PUBLIC_URL_PREFIX` in `.env.production.example`).
        return f"{self._public_url_prefix}/{key}"

    async def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as exc:
                # S3/R2 returns 404 for missing keys; anything else is a real
                # error and should surface to the caller.
                if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                    return False
                raise

        return await asyncio.to_thread(_head)
