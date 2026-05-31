---
description: Author per-entity and per-topic wiki summaries from the upstream Pepper&Carrot wiki sources. Reads `data/raw/wiki/` (curated bios), `data/raw/wiki-upstream/` (framagit scrape), and `data/world-graph/entities.yaml` (the canonical entity list). Writes one tight focused summary per entity to `data/wiki-summaries/entities/<slug>.md` and a handful of non-entity topic summaries to `data/wiki-summaries/topics/<slug>.md`. These summaries — not the raw wiki articles — become the documents the wiki ingestion pipeline embeds into the `wiki_v1` Chroma collection, so the chat-mode prompt sees ~600 words of focused entity context per question instead of 36 KB of multi-entity articles. Trigger phrases include "summarize the wiki", "regenerate wiki summaries", "rebuild wiki-summaries", "summarize-wiki".
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
---

# Summarize the Pepper&Carrot wiki into per-entity + per-topic focused docs

You (Claude Code) act as a one-shot author: read the upstream wiki +
world-graph entity list, synthesize tight, focused summaries (one per
entity, plus a few per non-entity topic), and write them as standalone
`.md` files. The wiki ingestion pipeline embeds these summaries
directly into the `wiki_v1` Chroma collection — they replace, not
supplement, the raw wiki articles.

**Why this skill exists.** Embedding raw wiki articles whole (or even
paragraph-chunked) lands 30+ KB of multi-entity text in the chat prompt
for a question like "Tell me about Truffel". The on-page model
(qwen2.5:7b) loses Truffel's two specific paragraphs in the noise and
ends up speculating or saying "I don't see Truffel in the context."
Per-entity summaries collapse the retrieval target to one focused
document per entity — top-3 retrieval lands ~600 words total, the
context is small enough that Post 8's OUTPUT RULES actually hold, and
the Truffel summary IS the wiki for Truffel.

**The artifact.** Like every other skill output in this project (page
descriptions, world-graph YAML), the summary `.md` files are durable,
version-controlled, hand-editable. Once they're good, fixes go straight
into the YAML — re-running this skill rewrites every summary. See ADRs
0004 (skill-driven page descriptions) and 0005 (skill-driven world
graph) for the architectural rationale.

## Inputs and outputs

| Read                                                   | Write                                                  |
|--------------------------------------------------------|--------------------------------------------------------|
| `data/world-graph/entities.yaml`                       | `data/wiki-summaries/entities/<slug>.md` (one per entity) |
| `data/raw/wiki/*.md` (curated bios)                    | `data/wiki-summaries/topics/<slug>.md` (a handful of topics) |
| `data/raw/wiki-upstream/*.md` (framagit scrape)        |                                                        |
| `data/wiki-summaries/{entities,topics}/*.md` (existing — preserve hand edits where reasonable) | |

If `data/raw/wiki-upstream/` doesn't exist, instruct the user to run
`cd ingestion && uv run python wiki_scraper.py` first and stop.

## Step 0 — Read the world-graph entities list

Open `data/world-graph/entities.yaml`. The 45 entities there are the
canonical list to write per-entity summaries for. Use the `slug` field
verbatim as the output filename (`<slug>.md`); the `name` field as the
`title:` frontmatter.

## Step 1 — Read source material

Required:
- `data/raw/wiki-upstream/characters.md` — long file with one `### <Name>`
  section per canonical character. Primary source for character summaries.
- `data/raw/wiki-upstream/creatures.md` — one section per named creature.
- `data/raw/wiki-upstream/places.md` — one section per place.
- `data/raw/wiki-upstream/magic-system.md` — covers the witch schools
  (Chaosah, Hippiah, Magmah, Aquah, Zombiah, Ah).
- `data/raw/wiki-upstream/history.md`, `timeline.md`, `time-system.md` —
  background lore for topic summaries.

Supplements (use to enrich a per-entity summary when the upstream is sparse):
- `data/raw/wiki/<slug>.md` — hand-curated short bios for pepper,
  carrot, chaosah, coriander, hereva, hippiah, magmah, shichimi, aquah.

## Step 2 — Preserve existing summaries where reasonable

If `data/wiki-summaries/entities/<slug>.md` already exists, READ IT and
decide whether the source material has actually changed in a way that
makes the existing summary stale. If the bio in `characters.md` is the
same as last time, **keep the existing summary** — the human may have
hand-edited it. Only rewrite when the upstream source has genuinely
new content.

(For the very first run, this directory doesn't exist yet — write every
summary from scratch.)

## Step 3 — Write per-entity summaries (tiered)

For each entity in `entities.yaml`, find its source material and write
a focused summary to `data/wiki-summaries/entities/<slug>.md`.

### Length tier

Pick the tier based on how plot-central the entity is:

- **Major (~250-300 words)** — Pepper, Carrot, the three Chaosah
  godmothers (Cayenne, Thyme, Cumin), the named rival witches
  (Saffron, Coriander, Shichimi), Prince Acren, the four primary
  covens (Chaosah, Hippiah, Magmah, Aquah), and Komona / Squirrel's End
  / Hereva. These are entities the reader will ask substantive
  questions about.
- **Minor (~100 words)** — every other entity. Includes most creatures
  (Phoenix, DragonCow, Hornuk, etc.), minor characters (Truffel,
  Mango, Yuzu, The Sage, Mayor of Komona, Apiaceae, Quassia, Camomile,
  Spirulina, Torreya), and the less-central covens (Zombiah, Ah) and
  places (Kingdom of Acren, Qualicity, Temples of Ah, Fairy Cave).

Tier is editorial — when in doubt, go shorter. Long answers from
qwen2.5:7b are the *failure* mode we're solving; less context = better
prompt-rule compliance.

### Voice

- **Plain prose, no markdown headers, no bullet points, no numbered
  lists.** This is the document the model reads at retrieval time —
  any markdown leaks into the answer (see Post 8). Flowing sentences
  only.
- **Present tense.** "Cayenne teaches Pepper spell-casting" not "taught".
- **Third person.** No "you" or "I".
- **Synthesize, don't quote.** Paraphrase the source material tightly.
- **Stick to facts in the source material.** Don't speculate. Don't
  invent backstory.

### Frontmatter

Every summary file MUST start with YAML frontmatter matching the
`WikiArticleData` contract in `ingestion/wiki_loader.py`:

```yaml
---
slug: cayenne
title: Cayenne
category: character
source_url: https://www.peppercarrot.com/en/wiki/Characters.html
---

Cayenne is the tall, rigid Chaosah witch who serves as Pepper's spell-
casting tutor. She is one of three godmothers who raised Pepper after
…
```

`slug` matches the entity's slug in `entities.yaml` (verbatim, no
underscores-to-hyphens normalization unless the entities.yaml itself
uses hyphens). `title` matches the entity's display name. `category`
is one of `character | creature | place | coven | object`. `source_url`
points to the upstream wiki article the summary derives from (the
upstream `.md` files have `source_url` in their frontmatter — copy
that). If the entity is derived purely from the curated bios,
`source_url` can be the project repo URL.

## Step 4 — Write topic summaries

Author summaries for non-entity lore that readers ask about but
doesn't map to a single graph node. Suggested topics (write ~200 words
each):

- `magic-system-overview` — what the six witch schools are, how
  Hereva's magic is organized, the relationships between schools.
- `history-of-hereva` — the broad arc: ancient covens, the Great War,
  current era. Source: `history.md`.
- `time-system` — how Hereva's calendar works (the months, the days),
  enough to disambiguate "Azarday" and "Pinkmoon" in episode dialogue.
  Source: `time-system.md`.
- `great-war` — the historical war between magic schools that shaped
  the current order. Source: `history.md`.
- `chaosah-tradition` — deeper than the Chaosah entity summary. The
  philosophy, the demon summoning, why it's feared. Useful when the
  reader asks "why is Chaosah feared?" rather than "what is Chaosah?".

Save to `data/wiki-summaries/topics/<slug>.md` with the same frontmatter
shape. `category: topic` for all of these.

Topic summaries don't need to mirror world-graph entities — they're
parallel coverage for "lore questions" vs "entity questions".

## Step 5 — Validate before exiting

After writing, validate that the files parse cleanly through the
existing wiki_loader:

```bash
cd ingestion && uv run python -c "
from pathlib import Path
from wiki_loader import load_wiki_articles
entities = load_wiki_articles(Path('../data/wiki-summaries/entities'))
topics = load_wiki_articles(Path('../data/wiki-summaries/topics'))
print(f'OK: {len(entities)} entity summaries, {len(topics)} topic summaries')
"
```

Fix any validation failures before reporting success.

## Step 6 — Report

Summarize what was written:
- Counts by tier (major / minor) and by kind.
- Topic summaries listed by slug.
- Reminder: edit the .md files directly to refine wording; only re-run
  this skill when the upstream wiki source actually changes.

> ⚠️ Re-running this skill rewrites every summary. If the human has
> hand-polished specific summaries, commit them first and `git diff`
> after a re-run.

## Notes

- **Idempotency caveat.** Same as `extract-world-graph`: layout is
  preserved across re-runs, summaries are not. The summaries are the
  thing the model writes, and re-running re-authors them. Hand-edits
  survive only if the source material hasn't changed (STEP 2 skips
  unchanged entities).
- **Slug alignment with the world graph is mandatory.** A summary at
  `entities/<slug>.md` whose slug doesn't match an entity in
  `entities.yaml` is fine in isolation but defeats the purpose — the
  wiki retrieval can pull it but nothing in the graph links back.
  Stick to the graph's slugs.
- **No bullet points, no markdown headers in the body.** Repeat this
  to yourself before authoring each summary. The model mirrors what it
  sees in context. Plain prose only.
- **Stay under the tier word count.** Major ~300 words, minor ~100
  words. A summary that runs long defeats the whole point — small
  context is what makes this approach better than embedding raw articles.
