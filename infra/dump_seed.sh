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

# Cheap sanity check — a dump with zero INSERT lines means dump_seed.sh ran
# against an empty local DB. The deploy will still go through, but the
# deployed app will have no episodes. Warn early rather than have the reader
# discover an empty episode picker after fly deploy.
insert_count=$(grep -c "^INSERT INTO " "$DUMP_TARGET" || true)
if [ "$insert_count" -eq 0 ]; then
    echo ""
    echo "[dump_seed] WARNING: 0 INSERT statements in the dump."
    echo "[dump_seed] Your local Postgres has schema but no data."
    echo "[dump_seed] Did you forget to ingest at least one episode + the wiki summaries"
    echo "[dump_seed] + the world-graph YAML before running this? See README.md Steps 7–11."
    echo "[dump_seed] You CAN proceed to fly deploy, but the deployed app will be empty."
else
    echo "[dump_seed] $insert_count INSERT statements captured."
    echo "[dump_seed] Next: fly deploy"
fi
