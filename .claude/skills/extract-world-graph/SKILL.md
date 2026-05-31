---
description: Extract the Pepper&Carrot world graph from the workshop's local sources — the seed wiki (`ingestion/wiki_seed.yaml`), the per-page description JSONs under `data/raw/ep*/pages/`, and the `data/world-graph/image_manifest.json` — then write `data/world-graph/entities.yaml` and `data/world-graph/relationships.yaml` that the world-graph loader consumes. Trigger phrases include "extract the world graph", "rebuild the world graph", "regenerate world graph YAML", "extract-world-graph".
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
---

# Extract the Pepper&Carrot world graph

You (Claude Code) act as a one-shot author: read the available source
material, synthesize a graph of named characters / creatures / places /
covens, then write the YAML pair the world-graph loader consumes.

The YAML is the durable artifact (see Post 9 and
`docs/decisions/0005-skill-driven-world-graph.md`). Once it's on disk
and loads cleanly, **fixes go into the YAML directly** — don't expect
re-runs of this skill to be deterministic. Re-run only when source
material changes (new episodes ingested, image manifest refreshed,
seed wiki expanded).

## Inputs and outputs

| Read                                                  | Write                                 |
|-------------------------------------------------------|---------------------------------------|
| `data/world-graph/image_manifest.json`                | `data/world-graph/entities.yaml`      |
| `ingestion/wiki_seed.yaml`                            | `data/world-graph/relationships.yaml` |
| `data/raw/ep*/pages/page_*.json`                      |                                       |
| `data/world-graph/entities.yaml` (if present)         |                                       |
| Optional: `data/raw/wiki-upstream/*.md` (full app)    |                                       |

The **full project** (Post 10's repo) maintains a scraped
`data/raw/wiki-upstream/` from framagit. The **workshop** ships with
only the small seed wiki — work from that plus the page JSONs from
ingested episodes, and let coverage grow organically as the reader
ingests more episodes via the `ingest-from-images` skill.

If the user requests **"extract to a draft"**, write to
`data/world-graph/draft/entities.yaml` and
`data/world-graph/draft/relationships.yaml` instead so the human can
`diff` before promoting. Otherwise write to the canonical paths.

## Step 0 — Read the image manifest

Open `data/world-graph/image_manifest.json`. It was produced by
`ingestion/wiki_image_scraper.py` and lists which image slugs have art
under `data/world-graph/images/<slug>-thumb.webp` /
`<slug>-display.webp`.

If the manifest **does not exist**, stop and instruct the user:

> The image manifest is missing. Run `cd ingestion && uv run python wiki_image_scraper.py` first, then re-run this skill.

## Step 1 — Read source material

**Required**:
- `ingestion/wiki_seed.yaml` — the hand-written articles seeded for
  wiki mode. Each article has `slug`, `title`, `category`, and `content`.
  This is the primary substance source for the workshop.

**Required where present**:
- `data/raw/ep*/pages/page_*.json` — per-page descriptions written by
  the `ingest-from-images` skill. Each JSON has a
  `characters_present` list (canonical names from the seeded
  `characters` table) and a `locations_or_concepts` list (places,
  schools, named potions). These are the primary evidence source for
  *when* an entity first appears.

**Optional supplement**:
- `data/raw/wiki-upstream/*.md` — if the user has scraped the full
  framagit wiki separately, treat these as authoritative for bios.
  In a fresh workshop clone they won't exist; that's fine.

## Step 2 — Read existing artifacts for cross-reference

### 2a. Preserve hand-tweaked layouts

If `data/world-graph/entities.yaml` already exists, parse it and
remember the `(slug → layout.{x,y})` mapping. When you assign layouts in
STEP 3, **reuse the existing layout for any slug that's already there**
— only assign fresh coordinates to brand-new slugs. The human may have
nudged positions and the skill must not clobber that work.

### 2b. Find debut episodes for characters

Glob `data/raw/ep*/pages/page_*.json` (one per described page; not every
episode has been ingested yet — that's fine). For every canonical
character name that appears in any `characters_present` array, find the
**earliest (episode_number, page_number)** where the name appears and
use that as `episode_debut` / `page_debut`.

Episode numbers come from the directory name (`ep01-…` → 1,
`ep11-…` → 11). Page numbers come from the filename (`page_006.json` → 6).

If a character is in the seed wiki but never appears in any described
page yet, default to `(1, 1)` and add a YAML comment `# confidence:
low — defaulted`.

### 2c. Debut for non-character entities

For places, covens, and creatures, look in:

1. The `locations_or_concepts` lists in page JSONs — same earliest-
   appearance logic as 2b. (A coven mentioned in dialogue, e.g.
   "Monsters of Chaosah at your service" in ep08, counts as a debut.)
2. The seed wiki content — if the article mentions a debut episode
   explicitly, use it.
3. Fall back to `(1, 1)` with `# confidence: low — defaulted`.

## Step 3 — Build the entity list

For each canonical character, place, coven, creature, or named object:

### Fields

- **slug** — lowercase-kebab-case, normally derived from the name.
  **Align with the image manifest where possible** to maximize image
  coverage: if the manifest has `chara_<slug>` for a character or
  `creature_<slug>` for a creature, prefer that exact slug. The display
  `name` field stays human-readable.
  - "The Sage" → `slug: sage` (if `sage` is in `manifest.characters`),
    `name: The Sage`.
  - "Mayor of Komona" → `slug: mayor` (if `mayor` is in the manifest),
    `name: Mayor of Komona`.
  - Some manifest slugs use underscores
    (e.g. `shapeshifter_transforming`); copy them verbatim — don't
    normalize to hyphens.
- **name** — human-readable display name, capitalized appropriately.
- **kind** — one of `character | creature | place | coven | object`.
- **summary** — 1-2 sentences of plain prose, present tense, synthesized
  from the seed wiki and/or the page JSONs. **NO markdown, NO bullet
  points, NO headers.** Don't quote sources verbatim — paraphrase
  tightly. Avoid spoilers beyond `episode_debut`/`page_debut`.
- **episode_debut**, **page_debut** — from STEP 2.
- **image_url**:
  - `kind: character` and `slug` is in `manifest.characters` →
    `"world-graph/images/<slug>-thumb.webp"`.
  - `kind: creature` and `slug` is in `manifest.creatures` →
    `"world-graph/images/<slug>-thumb.webp"`.
  - Otherwise → `null` (the frontend renders a kind-based fallback icon).
  - **Don't fuzzy-match.** If your slug doesn't match the manifest, fix
    the slug (per the alignment rule above) instead of guessing a path.
- **layout** — nested `{ x: float, y: float }`. Assign per the
  clustering rules below if the slug isn't already in
  `entities.yaml`; otherwise reuse.
- **character_slug** — set ONLY for `kind: character` entities;
  lower-cased match of the canonical name from the seeded `characters`
  table (e.g. `Pepper` → `character_slug: pepper`). The loader links the
  world-entity row to the canonical character via this. Leave null for
  non-characters and for characters not in the canonical roster.

### Layout clustering rules (apply only to NEW slugs)

- **Pepper** at origin: `{ x: 0, y: 0 }`.
- **Covens at compass points**:
  - Chaosah  `(-300, -200)` (top-left)
  - Hippiah  `( 300, -200)` (top-right)
  - Aquah    `(-300,  200)` (bottom-left)
  - Magmah   `( 300,  200)` (bottom-right)
  - Zombiah  `( 450,    0)`
  - Ah       `(-450,    0)`
- **Coven members**: in a small ring around their coven node, jittered
  ±60. E.g. Thyme / Cayenne / Cumin near Chaosah; Saffron near Magmah.
  Pepper stays at origin even though she's a Chaosah member.
- **Geographic locations**: horizontal strip at `y = -400`, spread
  along the x-axis (e.g. Komona at `(0, -400)`, Squirrel's End at
  `(-200, -400)`).
- **Creatures / familiars**: next to their owner with a small offset
  `(+30 x, +30 y)`. So Carrot is at `(30, 30)` (near Pepper), Yuzu
  near Shichimi.

These are starting positions, not law. The human will tweak by editing
the YAML. Your job is to seed sensible coordinates so the first render
isn't a mess.

## Step 4 — Build the relationship list

Look for these kinds in the seed wiki and the page JSONs, in priority order:

| Kind            | Direction (source → target)               | Example                              |
|-----------------|-------------------------------------------|--------------------------------------|
| `member_of`     | witch / demon → coven                     | Pepper → Chaosah                     |
| `godmother_of`  | godmother → Pepper                        | Thyme → Pepper                       |
| `apprentice_of` | apprentice → master                       | Pepper → Cayenne                     |
| `familiar_of`   | familiar → witch                          | Carrot → Pepper, Yuzu → Shichimi     |
| `lives_in`      | character / creature → place              | Pepper → Squirrel's End              |
| `located_in`    | coven / institution → place               | Magmah → Komona                      |
| `rival_of`      | witch → witch                             | Saffron → Pepper                     |
| `friend_of`     | witch → witch                             | Shichimi → Pepper                    |
| `family_of`     | relative → relative (generic kinship)     | Apiaceae → Coriander (grandmother)   |

When you author a `family_of` edge, put the specific relation
(grandmother, sister, sibling) in the `summary` field — the kind itself
stays generic so the taxonomy doesn't sprawl.

The frontend will color edges by `kind`, so consistent kinds matter more
than specific ones. Each relationship needs `episode_debut`,
`page_debut`. Rules:

- If the seed wiki or page JSONs pin a reveal episode, use it. Default
  to page 1 of that episode if the page isn't pinned, with
  `# confidence: low — page defaulted`.
- Otherwise, default to **the later of the two endpoints' debuts** and
  emit a YAML comment `# confidence: low — debut defaulted to endpoints`.
- Bidirectional kinds like `friend_of` / `rival_of`: author as a single
  directed edge — the renderer can choose to draw both ends the same.

## Step 5 — Validate before writing

After writing the YAML pair, run the loader's pydantic validation to
confirm the output parses and refers only to known slugs:

```bash
cd ingestion && uv run python -c "
from pathlib import Path
from world_graph_loader import load_world_graph
entities, rels = load_world_graph(Path('../data/world-graph'))
print(f'OK: {len(entities)} entities, {len(rels)} relationships')
"
```

If validation fails, FIX the YAML and re-run the validation before
exiting. Don't leave a broken YAML on disk — better to abort with a
clear error than to claim success.

(For a draft run, use `Path('../data/world-graph/draft')` instead.)

## Step 6 — Report to the user

Summarize:

1. **Total counts by kind** — character / creature / place / coven / object.
2. **Image coverage** — `image_url` set vs null, broken down by kind.
   Expect ~100% on `character` (every canonical character with framagit
   art) and ~100% on `creature` (most creatures with framagit art);
   0% on `coven` and `place` (the gaps are intentional; the frontend
   draws SVG fallbacks).
3. **Relationship counts by kind**.
4. **Low-confidence rows** — list slugs/edges marked with
   `# confidence: low` so the human knows what to audit.
5. **Reminder**:

> Edit the YAML directly to fix any wrong debuts, summaries, or layout
> coordinates. Don't re-run this skill expecting different output.
> Re-run only when source material changes — a new episode ingested, the
> image manifest refreshed, or the seed wiki expanded.

## Notes

- **Idempotent on layout, NOT on summary.** Re-running this skill will
  re-author every summary — even ones the human edited. If the human
  has hand-tuned summaries they want to keep, they should commit the
  YAML and `git diff` after a re-run, then keep what they want.
- **Layout reuse is mandatory.** STEP 2a is non-negotiable: the human's
  curated layout is more valuable than your fresh clustering.
- **Don't invent characters.** Stick to the seeded `characters` table
  for canonical names and the seed wiki's entity vocabulary. If a
  description mentions an unnamed creature in passing, it's not an entity.
- **Slug alignment with the image manifest is what unlocks coverage.**
  Most missed images come from slug mismatches. Always copy the
  manifest slug verbatim where one exists; let the human-readable
  `name` field do the disambiguation.
- **Workshop scope.** The seeded wiki has ~5 articles; ingested
  episodes may be ep01 + ep11 in some clones, ep01-ep12 in others. The
  skill should produce whatever graph is supportable from the inputs
  it finds — don't fabricate to fill in gaps. Coverage grows with the
  reader's ingestion progress.
