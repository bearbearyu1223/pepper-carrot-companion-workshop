# Data Model

PostgreSQL schema. SQLAlchemy 2.0 typed declarative models live in `backend/app/db/models.py`.

## Tables

### `episodes`

`NOT NULL` is marked explicitly; columns without it are nullable. Length bounds (`varchar(N)`) reflect the SQLAlchemy `String(N)` declarations and matter when those bounds are tight enough to bite.

| column            | type                      | notes |
|-------------------|---------------------------|-------|
| id                | uuid PK                   | |
| slug              | varchar(128) UK NOT NULL  | e.g. `ep01-pollution` |
| title             | varchar(256) NOT NULL     | display title |
| episode_number    | int NOT NULL              | 1, 2, 3… |
| language          | varchar(8) NOT NULL       | default `'en'`. 8 chars accommodates short BCP 47 tags (`en`, `fr-CA`) but would truncate longer subtags like `zh-Hant-TW` — bump the column if that ever matters |
| cover_image_url   | text                      | relative key, see CLAUDE.md |
| plot_summary      | text                      | written at ingestion, used for episode-level retrieval |
| credits_url       | text                      | link to original peppercarrot.com page |
| published_at      | timestamptz               | from peppercarrot.com metadata |
| ingested_at       | timestamptz NOT NULL      | server default `now()` |

### `pages`

| column              | type                            | notes |
|---------------------|---------------------------------|-------|
| id                  | uuid PK                         | |
| episode_id          | uuid FK→episodes NOT NULL       | `ON DELETE CASCADE` |
| page_number         | int NOT NULL                    | 1-indexed within an episode |
| image_url           | text NOT NULL                   | display variant, relative key |
| thumbnail_url       | text                            | thumbnail variant |
| original_url        | text                            | original PNG, relative key |
| ocr_text            | text                            | concatenated dialogue + SFX |
| visual_description  | text                            | the embedded text — flowing prose written by the `ingest-from-images` Claude Code skill |
| mood_tags           | text[] NOT NULL                 | small bag of adjective tags from the same `PageDescription` JSON. Default `[]` |
| image_metadata      | jsonb NOT NULL                  | `{width, height, blurhash, dominant_color}`. Default `{}` |

Unique constraint: `uq_pages_episode_page` on `(episode_id, page_number)`. (Declared as a `UniqueConstraint` in `models.py`, not a standalone `Index` — Postgres backs it with a unique index either way, but the SQLAlchemy mechanism is the constraint.)

### `characters`

| column                       | type                       | notes |
|------------------------------|----------------------------|-------|
| id                           | uuid PK                    | |
| name                         | varchar(128) UK NOT NULL   | "Pepper", "Carrot", "Shichimi" |
| aliases                      | text[] NOT NULL            | "the cat" → Carrot. Default `[]` |
| bio                          | text                       | |
| first_appearance_episode_id  | uuid FK→episodes           | `ON DELETE SET NULL` — deleting an episode clears this pointer rather than orphaning the character. Pepper survives a hypothetical delete of ep01 |
| image_url                    | text                       | reference portrait |

### `page_characters`

Many-to-many association between pages and characters. Powers character chips and "next appearance" navigation.

| column        | type                          |
|---------------|-------------------------------|
| page_id       | uuid FK→pages NOT NULL        |
| character_id  | uuid FK→characters NOT NULL   |

PK: `(page_id, character_id)`. Both FKs use `ON DELETE CASCADE` — deleting either side removes the appearance row.

### `wiki_articles`

| column      | type                       | notes |
|-------------|----------------------------|-------|
| id          | uuid PK                    | |
| slug        | varchar(128) UK NOT NULL   | e.g. `chaosah` |
| title       | varchar(256) NOT NULL      | |
| content     | text NOT NULL              | full article body (markdown) |
| category    | varchar(64)                | `school`, `location`, `concept`, `creature`, etc. |
| source_url  | text                       | peppercarrot.com URL |

### `commentary_notes`

David Revoy's process notes, scraped from his blog. Optionally tied to specific pages when the post mentions them. Powers the inline "✨ David's notes on this page" UI toggle (see `GET /api/pages/{id}/notes`). **Not used by chat retrieval** — the chat-time commentary mode that originally consumed these via Chroma was removed; the page-notes UI feature reads them directly from this table.

| column            | type                            | notes |
|-------------------|---------------------------------|-------|
| id                | uuid PK                         | |
| episode_id        | uuid FK→episodes NOT NULL       | `ON DELETE CASCADE` |
| page_number_hint  | int                             | when the note is page-specific |
| source_url        | text                            | original blog post URL |
| content           | text NOT NULL                   | paragraph or section content |

### `world_entities`

Nodes in the world-graph overlay (Phase 12). Characters, creatures, places, covens, and named objects from the *Pepper&Carrot* universe. Source-of-truth is `data/world-graph/entities.yaml`; the loader is delete-and-reinsert for relationships and upsert-by-slug for entities.

| column          | type                       | notes |
|-----------------|----------------------------|-------|
| id              | uuid PK                    | |
| slug            | varchar(128) UK NOT NULL   | natural key, e.g. `pepper`, `chaosah`, `komona` |
| name            | varchar(256) NOT NULL      | display name |
| kind            | varchar(32) NOT NULL       | `character` \| `creature` \| `place` \| `coven` \| `object` |
| summary         | text                       | 1–2 sentence blurb shown in the info card |
| image_url       | text                       | relative key, e.g. `world-graph/images/pepper-thumb.webp`. Null for covens/places/minor characters without framagit art — the frontend renders a kind-based SVG fallback |
| episode_debut   | int NOT NULL               | first episode the entity is on-page or referenced |
| page_debut      | int NOT NULL               | page within the debut episode |
| layout_x        | float NOT NULL             | curated x position for the full-world view |
| layout_y        | float NOT NULL             | curated y position for the full-world view |
| character_id    | uuid FK→characters         | `ON DELETE SET NULL` — links a `kind=character` entity to its row in the seeded `characters` roster (so chat retrieval and the world graph share the same canonical name). Cleared rather than cascaded so the world graph survives a re-seed of the character roster |
| created_at      | timestamptz NOT NULL       | server default `now()` |
| updated_at      | timestamptz NOT NULL       | server default `now()`, **`onupdate=now()`** — auto-bumps on every row mutation. The world tables are the only ones in the schema that carry `updated_at`, because they're the only tables hand-edited as the world graph evolves; the rest of the schema is append-only at ingestion time |

### `world_relationships`

Edges in the world-graph overlay. Source-of-truth is `data/world-graph/relationships.yaml`.

| column         | type                              | notes |
|----------------|-----------------------------------|-------|
| id             | uuid PK                           | |
| source_id      | uuid FK→world_entities NOT NULL   | `ON DELETE CASCADE` |
| target_id      | uuid FK→world_entities NOT NULL   | `ON DELETE CASCADE` |
| kind           | varchar(64) NOT NULL              | `member_of` \| `lives_in` \| `located_in` \| `familiar_of` \| `godmother_of` \| `apprentice_of` \| `family_of` \| `partner_of` \| `friend_of` \| `rival_of` \| `ally_of` \| `summoned_by` \| `teaches_at` |
| summary        | text                              | per-edge note (e.g. "Thyme is one of Pepper's three Chaosah-witch godmothers") |
| episode_debut  | int NOT NULL                      | first episode the relationship is revealed |
| page_debut     | int NOT NULL                      | |
| created_at     | timestamptz NOT NULL              | server default `now()` |
| updated_at     | timestamptz NOT NULL              | server default `now()`, **`onupdate=now()`** — same auditing pattern as `world_entities` |

Unique constraint `uq_world_relationships_src_tgt_kind` on `(source_id, target_id, kind)` so the loader can dedupe deterministically. All edges are directed; the kind tells you the direction.

### `chat_sessions`

| column        | type                              | notes |
|---------------|-----------------------------------|-------|
| id            | uuid PK                           | |
| user_id       | varchar(256)                      | optional email for the demo gate |
| episode_id    | uuid FK→episodes NOT NULL         | `ON DELETE CASCADE` |
| current_page  | int NOT NULL                      | default `1`. Updated as reader flips (`PATCH /api/sessions/{id}`) |
| created_at    | timestamptz NOT NULL              | server default `now()` |

### `chat_messages`

| column            | type                              | notes |
|-------------------|-----------------------------------|-------|
| id                | uuid PK                           | |
| session_id        | uuid FK→chat_sessions NOT NULL    | `ON DELETE CASCADE` |
| role              | varchar(16) NOT NULL              | `user` or `assistant` |
| mode              | varchar(32)                       | **nullable.** `page` or `wiki` on assistant turns (records which retrieval pipeline ran); `NULL` on user turns, which don't run through a retrieval pipeline. Anyone filtering `WHERE mode = 'page'` will silently drop user-turn rows — usually what you want for analytics, but worth knowing |
| content           | text NOT NULL                     | |
| retrieved_doc_ids | jsonb NOT NULL                    | array of Chroma IDs used to construct context. Default `[]`. **Critical for iteration.** |
| latency_ms        | int                               | **nullable.** End-to-end latency on assistant turns; `NULL` on user turns |
| token_counts      | jsonb NOT NULL                    | `{prompt, completion}` for assistant messages. Default `{}` |
| created_at        | timestamptz NOT NULL              | server default `now()` |

Composite index: `ix_chat_messages_session_created` on `(session_id, created_at)`. Every chat-history fetch ("messages in this session, in chronological order") scans this index — without it, listing a session's messages is a sequential scan that's cheap at 10 rows and painful at 10,000.

## Why these choices

### Why `retrieved_doc_ids` matters
When tuning retrieval, you want to look at any past assistant message and see exactly what context it had. Without this column, you'd have to rebuild it from logs — usually impossible because retrieval depends on the exact chunk store state at message time. This is the same pattern used in PersonaBench's run logging.

### Why `image_url` is a relative key, not a full URL
Storage backend changes (local → R2) become a config change instead of a database migration. The full URL is composed at API response time by the storage abstraction.

### Why `image_metadata` is JSONB instead of separate columns
Width, height, blurhash, dominant color are co-fetched and rarely queried in isolation. JSONB keeps the column count down and lets us add future fields (palette, alt-text, etc.) without migrations.

### Why two separate Chroma collections instead of one with a `type` filter
Each collection has a different optimal `k` and a different spoiler-filter posture, and the per-mode chat pipelines query exactly one of them (mutually exclusive — never both in the same turn). **Page mode** retrieves `k=3` from `pages_v1` with the spoiler filter excluding future pages **and** the current page itself (the orchestrator already feeds the current page's stored description into the prompt directly). **Wiki mode** retrieves `k=5` from `wiki_v1` with no spoiler filter (wiki facts about the universe aren't plot spoilers) and no similarity threshold (the user explicitly chose this mode). Separate collections make the retrieval code obvious about intent and let each have its own embedding-time chunking strategy (per-page for `pages_v1`, paragraph-chunked for `wiki_v1`).

A third collection `commentary_v1` existed earlier when the chat had a "commentary" mode that retrieved David Revoy's process notes. That mode was removed in favour of the page-notes UI feature (which reads `commentary_notes` directly from Postgres), and the Chroma collection was retired with it.

## Migrations

Use Alembic. Initial migration creates all the above. Subsequent migrations are generated with `alembic revision --autogenerate` after editing `models.py`. **Always** review the generated migration before applying — autogenerate gets enums, JSONB, and array types wrong sometimes.

## Seed data

`backend/app/db/seed.py` upserts the canonical character roster — 31 named characters drawn from the upstream Pepper&Carrot wiki (`data/raw/wiki-upstream/characters.md`). Includes Pepper, Carrot, the three Chaosah witches (Thyme, Cayenne, Cumin), other young witches (Saffron, Shichimi, Coriander, Camomile, Torreya), familiars (Truffel, Yuzu, Mango, Durian, Squeak), magic-school masters (Spirulina, Vanilla, The First Mermaid, Apiaceae, Soumbala, Botanic, Basilic, Quassia, Millet), adventurers (Brasic, Vinya, Frostir), and other named figures (Mayor of Komona, Prince Acren, The Sage, Fairies).

Run via:

```bash
cd backend && uv run python -m app.db.seed
```

Re-run safely — entries are upserted by name. The cast is read into the ingestion pipeline so the `ingest-from-images` skill anchors `characters_present` to canonical names and never invents new ones. **Re-seed before re-ingesting** if the cast list has been expanded since the last ingest run, or minor characters won't appear in `page_characters`.
