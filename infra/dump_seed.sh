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

# Cheap sanity check — a dump against an empty local DB still emits the
# schema (CREATE TABLE, ALTER TABLE, etc.) but no data rows. Warn so the
# operator notices before fly deploy lands an empty episode picker.
#
# pg_dump's plain format uses COPY (not INSERT) for data by default, so
# we count actual data rows between `COPY ... FROM stdin;` markers and
# the `\.` terminator. We also count INSERT statements as a fallback for
# the rare case someone passes --inserts to pg_dump explicitly.
data_rows=$(awk '
    /^COPY .* FROM stdin;$/ { in_copy=1; next }
    /^\\\.$/                { in_copy=0; next }
    in_copy && NF > 0       { count++ }
    END                     { print count+0 }
' "$DUMP_TARGET")
# `grep -c` prints "0" AND exits status 1 on no matches; `|| true` lets
# `set -e` survive the status-1 case without grep adding a second line.
copy_count=$(grep -c "^COPY " "$DUMP_TARGET" || true)
insert_count=$(grep -c "^INSERT INTO " "$DUMP_TARGET" || true)
total_data=$((data_rows + insert_count))

if [ "$total_data" -eq 0 ]; then
    echo ""
    echo "[dump_seed] WARNING: 0 data rows in the dump (schema only)."
    echo "[dump_seed] Your local Postgres has schema but no data."
    echo "[dump_seed] Did you forget to ingest at least one episode + the wiki summaries"
    echo "[dump_seed] + the world-graph YAML before running this? See README.md Steps 7–11."
    echo "[dump_seed] You CAN proceed to fly deploy, but the deployed app will be empty."
else
    echo "[dump_seed] Captured $copy_count tables, $data_rows data rows."
    echo "[dump_seed] Next: fly deploy"
fi
