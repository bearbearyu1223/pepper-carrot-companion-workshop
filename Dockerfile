# Backend container for the Fly deployment (Post 10).
#
# Image contents:
#   • The Python venv (frozen against backend/uv.lock) — same versions as dev.
#   • The FastAPI app code (backend/app + backend/alembic).
#   • The small data assets that ship inside the image:
#       data/seed.sql        — produced by infra/dump_seed.sh before `fly deploy`.
#       data/chroma          — the embedded vector store (pages_v1 + wiki_v1).
#       data/world-graph     — entities.yaml + relationships.yaml + image_manifest.json.
#   • The entrypoint: `entrypoint.sh seed` (run as Fly's release_command)
#     restores seed.sql into a fresh Neon DB before the app boots; with no
#     args it exec's uvicorn straight away so the socket binds immediately.
#
# Episode images are NOT baked — they go to Cloudflare R2 (STORAGE_BACKEND=r2).
# See docs/deployment.md for the end-to-end deploy.

# ── Stage 1: install deps into a venv (cached layer) ──────────────────────────
FROM python:3.11-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock /app/
RUN uv sync --frozen --no-dev


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim

# psql is needed by infra/entrypoint.sh to restore data/seed.sql in the
# release_command (`entrypoint.sh seed`).
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    LOCAL_IMAGE_DIR=/app/data/images \
    CHROMA_PERSIST_DIR=/app/data/chroma

COPY backend/app /app/app
COPY backend/alembic /app/alembic
COPY backend/alembic.ini /app/alembic.ini

# Bake small data: chroma vectors + world-graph YAML.
# Episode page images are NOT baked — they go to R2 (see docs/deployment.md).
COPY data/chroma /app/data/chroma
COPY data/world-graph /app/data/world-graph

# DB seed produced by infra/dump_seed.sh before `fly deploy`. If this COPY
# fails with "no source files were specified for source: data/seed.sql",
# you skipped Step 4 of docs/deployment.md — run `./infra/dump_seed.sh`
# from the repo root first, then re-run `fly deploy`. The canonical pattern
# is `./infra/dump_seed.sh && fly deploy` so the two steps stay ordered.
COPY data/seed.sql /app/data/seed.sql

COPY infra/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
