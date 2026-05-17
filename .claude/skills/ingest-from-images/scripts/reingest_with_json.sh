#!/usr/bin/env bash
# Run the ingestion pipeline for one episode using VISION_PROVIDER=json.
#
# Flips VISION_PROVIDER to 'json' in .env for the duration of the run, then
# reverts to whatever the original value was — even if ingestion fails or
# the user Ctrl-Cs out. Sibling JSON files (page_NNN.json next to each
# page_NNN.jpg) supply the descriptions; JsonFileVisionClient reads them.
#
# Usage (from anywhere):
#   ./.claude/skills/ingest-from-images/scripts/reingest_with_json.sh <episode-slug>
#
# Example:
#   ./.claude/skills/ingest-from-images/scripts/reingest_with_json.sh ep07-the-wish

set -euo pipefail

slug="${1:?Usage: $0 <episode-slug>}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
ENV_FILE="$ROOT/.env"
EP_DIR="$ROOT/data/raw/$slug"

if [[ ! -d "$EP_DIR" ]]; then
  echo "Episode directory not found: $EP_DIR" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo ".env not found at $ENV_FILE" >&2
  exit 1
fi

# Capture the original VISION_PROVIDER line so we can put it back exactly
# as it was (preserves comments/spacing on adjacent lines).
orig_line=$(grep -E '^VISION_PROVIDER=' "$ENV_FILE" || true)
if [[ -z "$orig_line" ]]; then
  echo "VISION_PROVIDER= line not found in $ENV_FILE" >&2
  exit 1
fi

# Always restore on exit, even on Ctrl-C or ingest failure. macOS sed needs
# the empty -i argument; Linux would use -i without it.
restore() {
  sed -i '' "s|^VISION_PROVIDER=.*|$orig_line|" "$ENV_FILE"
  echo "[reverted] $orig_line"
}
trap restore EXIT

sed -i '' "s|^VISION_PROVIDER=.*|VISION_PROVIDER=json|" "$ENV_FILE"
echo "[set] VISION_PROVIDER=json (will revert on exit)"

cd "$ROOT/ingestion"
uv run python ingest.py --episode-dir "$EP_DIR"
