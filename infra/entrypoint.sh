#!/bin/sh
# Container entrypoint for the Fly deployment (Post 10).
#
# On the FIRST boot — Neon is empty, the `episodes` table doesn't exist —
# psql restores /app/data/seed.sql to populate the schema + data the
# backend depends on. On every subsequent boot (Neon already has data) the
# restore is skipped and uvicorn starts immediately.
#
# Idempotent: the only side effect is the SQL restore, and that's guarded
# by the existence check.

set -e

if [ -z "$POSTGRES_RESTORE_URL" ]; then
    echo "[entrypoint] POSTGRES_RESTORE_URL not set; skipping seed check."
else
    have_episodes="$(psql "$POSTGRES_RESTORE_URL" -tAc \
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='episodes'")"
    if [ "$have_episodes" != "1" ]; then
        echo "[entrypoint] Seeding Postgres from /app/data/seed.sql ..."
        psql "$POSTGRES_RESTORE_URL" < /app/data/seed.sql
        echo "[entrypoint] Seed complete."
    else
        echo "[entrypoint] Postgres already seeded (episodes table present); skipping."
    fi
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
