#!/bin/sh
# Container entrypoint for the Fly deployment (Post 10).
#
# Two modes, dispatched on the first argument:
#
#   • `seed`   — restore /app/data/seed.sql into a fresh Neon DB, then exit.
#                Run as Fly's release_command (see fly.toml [deploy]) so it
#                executes in a temporary release machine BEFORE the app
#                machine boots. Idempotent: guarded by an information_schema
#                existence check, so a re-deploy against an already-seeded DB
#                logs "already seeded" and exits 0.
#
#   • (no arg) — the normal app boot. exec uvicorn immediately so the app
#                machine binds 0.0.0.0:8000 with no seed step in the way.
#                This is what removes the "not listening on the expected
#                address" warning: the slow first-boot psql restore no longer
#                races Fly's post-launch listen check, because it has moved
#                out of the boot path and into the release command.
#
# Fly appends the release_command to the image ENTRYPOINT, so the release
# machine runs `/app/entrypoint.sh seed` while the app machine runs
# `/app/entrypoint.sh` with no arguments.

set -e

if [ "$1" = "seed" ]; then
    if [ -z "$POSTGRES_RESTORE_URL" ]; then
        echo "[seed] POSTGRES_RESTORE_URL not set; skipping seed check."
        exit 0
    fi
    have_episodes="$(psql "$POSTGRES_RESTORE_URL" -tAc \
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='episodes'")"
    if [ "$have_episodes" != "1" ]; then
        echo "[seed] Seeding Postgres from /app/data/seed.sql ..."
        psql "$POSTGRES_RESTORE_URL" < /app/data/seed.sql
        echo "[seed] Seed complete."
    else
        echo "[seed] Postgres already seeded (episodes table present); skipping."
    fi
    exit 0
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
