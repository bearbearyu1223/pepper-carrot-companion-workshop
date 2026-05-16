# ADR 0003: Storage abstraction for images

**Status**: Accepted
**Date**: 2026-04-25

## Context

Images need to live somewhere. In dev, the local filesystem is the obvious choice — fast, no auth, no cost, easy to inspect. In production, R2 (or S3) is the right choice — CDN integration, no egress costs (R2), durability.

Both backends need to behave the same from the rest of the system's perspective.

## Decision

Define a `Storage` Protocol with two implementations: `LocalStorage` and `R2Storage`. Database stores a relative key (e.g. `episodes/ep01-pollution/pages/001-display.webp`). The storage backend resolves relative keys to URLs and handles uploads/reads.

```python
class Storage(Protocol):
    async def put(self, key: str, content: bytes, content_type: str) -> None: ...
    async def url_for(self, key: str) -> str: ...
    async def exists(self, key: str) -> bool: ...

class LocalStorage(Storage): ...   # writes to LOCAL_IMAGE_DIR, serves via FastAPI StaticFiles
class R2Storage(Storage): ...      # boto3 against R2 endpoint
```

In `LocalStorage`, `url_for` returns a URL like `http://localhost:8000/images/<key>` — the FastAPI app mounts a `StaticFiles` route at `/images` pointing at `LOCAL_IMAGE_DIR`.

In `R2Storage`, `url_for` returns a URL on the configured public domain (`R2_PUBLIC_URL_PREFIX + "/" + key`).

## Consequences

**Positive**
- Local→cloud migration is config-only. No data migration needed apart from copying files into the bucket.
- Routes return image URLs that "just work" in either environment.
- Easy to mock for tests.

**Negative**
- Local serving via FastAPI is fine for dev but won't scale. Acceptable because production won't use it.
- One missed abstraction would leak: signed URL TTLs. If we ever need signed URLs for the cloud backend, the interface needs `url_for(..., ttl: timedelta | None)`. Add it then, not now.

## Notes on key structure

Keys are hierarchical for ergonomics, not because the storage understands directories. Layout:

```
episodes/<episode-slug>/pages/<NNN>-<variant>.webp
episodes/<episode-slug>/cover-<variant>.webp
characters/<character-slug>.webp
wiki/<article-slug>/<image>.webp
```

Three-digit zero-padded page numbers so directory listings sort correctly.

## What this doesn't cover

- **Image transformation at request time** (e.g., dynamic resizing). All variants are produced during ingestion. Adding runtime transforms would justify a separate ADR.
- **Lifecycle management** (deleting old variants, archival). Out of scope for the demo.
