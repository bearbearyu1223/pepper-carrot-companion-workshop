---
description: Ingest a Pepper&Carrot episode by describing each page image yourself (via the Read tool) and writing PageDescription JSON files that the JsonFileVisionClient picks up. This is the standard ingestion path for the project — there is no other vision provider. Trigger phrases include "ingest episode N", "ingest episode N from images", "describe pages for episode N", "re-describe pages for episode N", "describe the missing pages of episode N", "ingest-from-images", "set up episode N for the chat".
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
---

# Ingest a Pepper&Carrot episode from page images

This skill is the **only** ingestion path for the project. You (Claude Code)
act as the vision provider: read each page image visually, write a
structured `PageDescription` JSON next to it, then run the ingestion
script. `JsonFileVisionClient` consumes your JSONs and the rest of the
pipeline (image processing, storage, DB upsert, character linking, Chroma
re-embed, plot summary) runs unchanged.

There are no Ollama or Anthropic vision clients in the codebase — they were
removed in favour of this approach because the descriptions you produce
visually are higher quality and free.

## Inputs

Identify the target episode from the user's request:
- A slug like `ep07-the-wish` → use directly.
- A number like "episode 7" / "ep7" → resolve via `ls data/raw/ | grep '^ep07-'`.
  If multiple match, ask the user.
- No episode named → list `data/raw/ep*` directories and ask which one.

## Step 1 — Read the cast list

Anchor your descriptions to canonical character names. Pull them from the DB:

```bash
docker exec peppercarrot-postgres psql -U peppercarrot -d peppercarrot -tA \
  -c "SELECT name FROM characters ORDER BY name;"
```

Hold this list in mind while describing. Use the canonical name when a
character is identifiable (`Pepper` not "the young witch", `Mango` not
"the bird"). If a creature has no canonical name (e.g., a one-off
animal-of-the-week), describe it generically in `visual_description` and
omit it from `characters_present` rather than inventing a name.

## Step 2 — List the pages

```bash
ls data/raw/<slug>/pages/page_*.jpg
```

Note the count and process them in order so narrative continuity carries
forward.

## Step 3 — Describe each page

For each `page_NNN.jpg`, in order:

1. Use the `Read` tool to view the image.
2. Compose a `PageDescription` matching this schema (every field required):

   ```json
   {
     "visual_description": "3-5 sentences of flowing prose, present tense. NO markdown, NO panel-by-panel breakdown (no 'Panel 1:', 'Setting:', 'Mood:' headers), NO bullet points. Describe what the page shows as a coherent narrative paragraph that a friend reading over your shoulder would understand.",
     "dialogue": [
       {"speaker": "Pepper", "text": "verbatim from the speech bubble"},
       {"speaker": null, "text": "SFX IN CAPS"}
     ],
     "characters_present": ["Pepper", "Carrot"],
     "locations_or_concepts": ["Komona", "the Potion Contest"],
     "mood_tags": ["surprised", "comedic"]
   }
   ```

3. Write to `data/raw/<slug>/pages/page_NNN.json` — sibling of the image.

### Field rules

- **visual_description**: prose only. No markdown, no headers, no bullets.
  Resist the panel-by-panel format — the whole point of this skill is to
  produce clean prose that won't leak structure into chat answers later.
- **dialogue**: one entry per speech bubble or caption, in reading order.
  Verbatim — don't paraphrase. `speaker = null` for SFX, narration,
  unidentified speakers, and creatures without canonical names.
- **characters_present**: only canonical names from the cast list.
  Omit unnamed creatures; don't invent.
- **locations_or_concepts**: named places (Komona, Squirrel's End),
  magic schools (Chaosah, Hippiah, Magmah, Aquah, Zombiah), potions
  ("Potion of Flight"), currencies ("Ko"), universe-specific concepts.
- **mood_tags**: 1-4 short adjectives ("playful", "tense", "wondrous",
  "comedic", "action", "quiet", "triumphant").

## Step 4 — Validate the JSONs

Before ingesting, confirm every JSON parses against the model:

```bash
cd backend && uv run python -c "
from pathlib import Path
from app.clients.vision import PageDescription
for p in sorted(Path('../data/raw/<slug>/pages').glob('*.json')):
    PageDescription.model_validate_json(p.read_text())
    print(f'{p.name}: OK')
"
```

Fix any failures before proceeding.

## Step 5 — Ingest

The wrapper script flips `VISION_PROVIDER=json` for the duration of the run
and reverts on exit (even on failure). Invoke it via an **absolute path** so
it works regardless of which directory you're currently in (`./...` would
resolve against your current working directory, which is rarely the project
root):

```bash
# Resolve the project root from anywhere the Bash tool happens to be in:
ROOT=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null \
       || echo /Users/hanyu/Documents/GitHub/peppercarrot-companion-app)
"$ROOT/.claude/skills/ingest-from-images/scripts/reingest_with_json.sh" <slug>
```

(The fallback path is hardcoded for this machine; the `git rev-parse` form
works in any clone of the repo.)

## Step 6 — Verify

```bash
docker exec peppercarrot-postgres psql -U peppercarrot -d peppercarrot -c \
  "SELECT episode_number, slug, plot_summary IS NOT NULL AS has_summary, \
   (SELECT COUNT(*) FROM pages WHERE episode_id = e.id) AS page_count \
   FROM episodes e WHERE slug = '<slug>';"
```

Expect `has_summary = t` and `page_count` matching the number of JSONs you wrote.

Then run a final sanity-check that page-character links populated:

```bash
docker exec peppercarrot-postgres psql -U peppercarrot -d peppercarrot -c \
  "SELECT p.page_number, STRING_AGG(c.name, ', ' ORDER BY c.name) AS chars \
   FROM pages p \
   LEFT JOIN page_characters pc ON pc.page_id = p.id \
   LEFT JOIN characters c ON c.id = pc.character_id \
   WHERE p.episode_id = (SELECT id FROM episodes WHERE slug = '<slug>') \
   GROUP BY p.page_number ORDER BY p.page_number;"
```

## Notes

- **Idempotent**: re-running overwrites existing JSONs and re-upserts pages.
  Safe to run multiple times.
- **Scope is per-episode**: only the episode you target is touched. Other
  episodes' DB rows and Chroma chunks are unaffected.
- **Chat layer is unaffected**: `JsonFileVisionClient.answer_about_page`
  raises NotImplementedError, but that's only called by chat orchestration
  for runtime page-Q&A — not by ingestion. As long as you revert
  `VISION_PROVIDER` (the wrapper script does this), the chat layer
  continues to use the configured ollama/anthropic provider.
- **Continuity matters**: process pages in order so story beats from earlier
  pages inform how you describe later ones (the schema doesn't carry
  previous-page context for this client, but YOU do via the conversation).
