#!/bin/sh
# Dump the local Postgres into data/seed.sql for baking into the Docker
# image. Run before `fly deploy` whenever ingestion has changed the DB
# (new episode ingested, world-graph YAML edited, character roster
# tweaked, etc.).
#
# pg_dump produces a plain-format SQL script that psql can replay byte-
# for-byte on the empty Neon database. We drop owner/grants/privileges
# because Neon's role name differs from local, and Postgres rejects the
# ALTER OWNER lines a default dump emits.

set -e

cd "$(dirname "$0")/.."

DUMP_TARGET="data/seed.sql"

# Match docker-compose.yml defaults; override via env if customised.
PGUSER="${POSTGRES_USER:-peppercarrot}"
PGPASSWORD="${POSTGRES_PASSWORD:-peppercarrot_dev}"
PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDATABASE="${POSTGRES_DB:-peppercarrot}"

export PGPASSWORD

echo "[dump_seed] Dumping $PGDATABASE@$PGHOST:$PGPORT -> $DUMP_TARGET ..."
pg_dump \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    --no-owner --no-acl --no-privileges \
    --format=plain \
    > "$DUMP_TARGET"

size=$(wc -c < "$DUMP_TARGET" | tr -d ' ')
echo "[dump_seed] Wrote $DUMP_TARGET ($size bytes)."
