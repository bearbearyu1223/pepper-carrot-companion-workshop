# CLAUDE.md

This document orients Claude Code (and human contributors) to the **workshop starter** for the Pepper & Carrot Reading Companion. **Read this first** before making changes.

> **About the scope.** This repository is a deliberately scoped slice of a larger project — it contains everything needed to reproduce [Post 2](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-workshop/) (workshop setup) through **Post 7** (streaming chat + schema-constrained suggestion chips) of the blog series, and nothing else. The full project repository (world-graph overlay, cloud deploy) goes up alongside the deploy guide in Post 10. References below to features not yet present here (e.g., the world-graph overlay, the hardened production prompts, cloud infra) belong to Posts 8–10 and apply to the full project; they're kept in this file so the conventions stay forward-compatible.

---

## What this project is

A local-first web application that turns David Revoy's CC BY-licensed webcomic *Pepper & Carrot* into an interactive flipbook with a context-aware AI reading companion. The chat layer knows the reader's current page (or two-page spread) and offers two question paths the user picks via UI chips: **page** (questions grounded in the visible spread + prior pages, spoiler-filtered) and **wiki** (questions grounded in retrieved *Pepper & Carrot* universe lore). After each answer, two follow-up suggestion chips appear; each chip is tagged with its target mode so a click sends the next question through the right pipeline.

This is a **portfolio / demo project**. Optimize for clarity, quality, and a clean architecture story — not feature breadth.

## What this project is NOT

- Not a SaaS. No multi-tenancy, no billing, no admin panel.
- Not optimized for scale. Single VM is the target; ChromaDB embedded in-process is fine (in Post 6).
- Not a generic comic platform. The data model and prompts are tuned for Pepper & Carrot specifically.
- Not for content the project does not have rights to.

---

## Architecture (one paragraph)

A FastAPI backend orchestrates everything. It reads metadata from PostgreSQL, retrieves vector chunks from ChromaDB (Post 6), fetches images from local storage (cloud later), and calls model providers (local Ollama by default for chat + embeddings; Anthropic API as a swap-in). A React + StPageFlip frontend (Post 5) renders the flipbook, with a streaming chat panel beside it (Post 7); the world-graph overlay is added in Post 9 in the full project. An offline ingestion script (Post 4) populates Postgres + Chroma + the image store from raw episode assets. Page descriptions are produced by the `ingest-from-images` Claude Code skill (Post 4). Three things are abstracted behind interfaces because they change between local and cloud: chat provider, embedding provider, and image storage. **The workshop starter implements those three interfaces, the data model and Alembic migrations, the offline ingestion pipeline, and a typed REST surface plus a flipbook reader UI.**

---

## Repository layout (workshop starter)

```
pepper-carrot-companion-workshop/
├── CLAUDE.md                ← you are here
├── README.md                ← human-facing setup guide, mapped to Posts 2–7
├── docker-compose.yml       ← postgres + pgadmin
├── .env.example             ← copy to .env and fill in
├── docs/
│   ├── data-model.md        ← schema and rationale (all 10 tables)
│   └── decisions/           ← ADRs 0001 (local-first), 0002 (provider), 0003 (storage)
├── backend/
│   ├── pyproject.toml + uv.lock
│   ├── alembic.ini + alembic/    ← env.py + initial-schema + world-graph migrations
│   ├── app/
│   │   ├── main.py          ← FastAPI app: lifespan, CORS, /api/episodes, /images mount, /health
│   │   ├── config.py        ← typed Settings (pydantic-settings)
│   │   ├── api/             ← HTTP API surface
│   │   │   ├── episodes.py  ←   GET /api/episodes + /api/episodes/{slug} (Post 5)
│   │   │   ├── sessions.py  ←   POST /api/sessions + PATCH /api/sessions/{id} (Post 6)
│   │   │   └── messages.py  ←   POST /api/sessions/{id}/messages — SSE chat stream (Posts 6–7)
│   │   ├── clients/         ← provider abstractions ★
│   │   │   ├── storage.py   ←   Storage + LocalStorage (+ R2Storage stub)
│   │   │   ├── embedding.py ←   EmbeddingClient + Ollama + sentence-transformers
│   │   │   ├── chat.py      ←   ChatClient + Ollama + Anthropic (stream + complete)
│   │   │   ├── vision.py    ←   VisionClient + JsonFileVisionClient (used in Post 4)
│   │   │   └── __init__.py  ←   the factory
│   │   ├── core/
│   │   │   └── prompts.py   ← PAGE / WIKI / SUGGESTIONS prompts (Posts 6–7) ★
│   │   ├── retrieval/
│   │   │   └── service.py   ← RetrievalService + the spoiler filter (Posts 6–7) ★
│   │   ├── orchestration/
│   │   │   └── chat.py      ← ChatOrchestrator.stream_response — retrieve→prompt→stream+chips (Posts 6–7) ★
│   │   └── db/
│   │       ├── models.py    ← 10 SQLAlchemy 2.0 typed models
│   │       ├── session.py   ← async engine + session factory
│   │       └── seed.py      ← 31-character canonical roster
│   └── tests/               ← storage, embedding, episodes-api, retrieval, chat (parser + SSE)
├── frontend/                ← React + Vite + TS flipbook UI + chat panel (Posts 5, 7)
│   ├── package.json
│   ├── vite.config.ts       ← dev proxy for /api and /images
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── App.tsx          ← picker ↔ reader switch; opens a session, PATCHes page flips
│       ├── main.tsx
│       ├── api/
│       │   ├── client.ts    ← episodes + sessions + streamMessage (SSE consumer)
│       │   └── types.ts     ← TS mirrors of the Pydantic models + chat types
│       ├── components/
│       │   ├── EpisodePicker.tsx
│       │   ├── Flipbook.tsx ← StPageFlip wrapped in React via a ref
│       │   └── ChatPanel.tsx ← streaming chat + suggestion chips (Post 7)
│       └── styles/global.css
├── ingestion/
│   ├── acquire.py           ← peppercarrot.com episode downloader (Post 2 step)
│   ├── ingest.py            ← Post 4 Stage 2 orchestrator (episodes)
│   ├── ingest_wiki.py       ← wiki seed → wiki_articles + wiki_v1 (Post 7)
│   ├── wiki_seed.yaml       ← hand-written seed wiki articles (Post 7)
│   ├── images.py            ← Pillow image variants + blurhash + dominant color
│   ├── episode_loader.py    ← validates metadata.yaml + lists page files
│   ├── repository.py        ← async DB upsert helpers (pages + wiki)
│   └── chroma_writer.py     ← pages_v1 + wiki_v1 embedding writes
└── data/                    ← gitignored — Postgres bind mount + downloaded episodes
```

★ = the most architecturally important code. Read these first when changing model behavior. The `clients/` provider abstractions are the topic of Post 3; the `retrieval/` + `orchestration/` + `core/prompts.py` chat layer is the topic of Post 6 (retrieval + the spoiler boundary) and Post 7 (streaming + chips).

**Files mentioned in the conventions below that aren't yet in this repo** (they land in later posts and live in the full project): the world-graph overlay in `frontend/src/components/` and the `extract-world-graph` Claude Code skill (Post 9), Modal / Fly / R2 infra (Post 10). The hardened production prompts (Post 8) expand the existing `core/prompts.py` in place.

---

## Conventions Claude must follow

### 1. Provider abstraction is mandatory

**Never** import a swappable provider SDK — `anthropic`, `openai`, `boto3`, or `ollama` — directly outside of `backend/app/clients/`. Every model and storage provider goes through an interface, and that is what makes local→cloud migration trivial.

The one deliberate exception is **ChromaDB**. It's the single vector store, not a provider with a local/cloud alternative to swap between, so it isn't hidden behind a `clients/` Protocol. The `chromadb` SDK is imported in exactly two places — `backend/app/retrieval/service.py` (read side) and `ingestion/chroma_writer.py` (write side) — and nowhere else. Knowing *what deserves an abstraction and what doesn't* is part of the design story: three things change between local and cloud (chat, embeddings, image storage), so those three are abstracted; the vector store doesn't, so it isn't.

```python
# YES
from app.clients.embedding import EmbeddingClient
from app.clients import get_embedding_client
client: EmbeddingClient = get_embedding_client(settings)
vec = await client.embed_batch(["Pepper picks up a glowing potion"])

# NO
import httpx
httpx.post("http://localhost:11434/api/embed", ...)  # ← never in routes, services, or ingestion
```

When asked to add a new provider, the change is: add a new implementation class in `clients/`, register it in the factory in `backend/app/clients/__init__.py`, add a config option. No caller code changes. This is the topic of Post 3.

### 2. Spoiler safety is enforced at the data layer *(active from Post 6)*

Retrieval queries **always** filter by the reader's position before ranking. The boundary is *lexicographic* on `(episode, page)` — an earlier episode (any page), OR the current episode up to an earlier page — **not** the flat `episode_number <= E AND page_number <= P`. The flat form is a real bug: it would drop page 20 of episode 1 while the reader is on page 3 of episode 2, even though episode 1 is fully behind them. The Chroma `where` clause:

```python
{"$or": [
    {"episode_number": {"$lt": current_episode}},
    {"$and": [
        {"episode_number": current_episode},
        {"page_number": {"$lt": current_page}},  # $lt: the current page is fed to the prompt directly
    ]},
]}
```

This is non-negotiable, and it does not rely on prompt instructions. The boundary integers come from the `chat_sessions` row (server-side reading progress), never from the user's message — so a jailbreak prompt has nothing to widen. The enforcing code is `RetrievalService._spoiler_filter` in `backend/app/retrieval/service.py`; the proof is `backend/tests/test_retrieval.py`.

### 3. All system prompts live in `core/prompts.py` *(active from Post 6)*

Per-mode prompts compose shared blocks for voice, spoiler discipline, and response format. `PAGE_MODE_SYSTEM` and `WIKI_MODE_SYSTEM` (Posts 6–7) share `_SHARED_VOICE` and `_SPOILER_DISCIPLINE`; `SUGGESTIONS_SYSTEM` (Post 7) drives the follow-up-chip generation, with the chip *shape* enforced by `_SUGGESTIONS_SCHEMA` in `orchestration/chat.py`. Post 8 expands all three with the stricter formatting rules the production prompts carry. Keep them as module-level constants. Never inline a prompt in a route or service.

### 4. Database is the source of truth, Chroma stores embeddings + IDs *(active from Post 6)*

ChromaDB stores `(embedding, metadata, document_id)` tuples. The actual text content lives in Postgres. This means: when retrieving, query Chroma for IDs, then fetch full content from Postgres. Do not duplicate text across stores. The schema in this starter already reflects this convention — `pages.visual_description` and `wiki_articles.content` are the canonical text columns.

### 5. Image URLs in the database are relative keys

`pages.image_url` stores a relative key like `episodes/ep01-pollution/pages/001-display.webp`, not a full URL. The full URL is composed at API response time using the configured storage backend (`LocalStorage.url_for()` or `R2Storage.url_for()`). This way, swapping storage backends (local → R2) is a config change, not a migration. Active in this starter.

### 6. Async everywhere

FastAPI is async. SQLAlchemy uses the async session. Model client calls are async. `LocalStorage.put` uses `aiofiles`; `LocalStorage.exists` wraps `Path.exists()` in `asyncio.to_thread`. Don't introduce sync paths without a real reason.

### 7. Type everything

Pydantic models for API I/O. SQLAlchemy 2.0 typed declarative models for DB (`Mapped[X]` annotations on every column). `Protocol` types for client interfaces. The codebase passes `mypy --strict`. If you add types that break it, fix the breakage.

### 8. Tests for retrieval logic and prompt assembly *(active from Post 6)*

These are the two places bugs hide. Other things can be tested by hand for the demo. Don't write exhaustive unit tests for plumbing. The current `tests/` cover `LocalStorage` (the only non-trivial behavior in the storage layer), both embedding clients (because the wire-format diff between Ollama and sentence-transformers is exactly the seam that a bug would hide in), the episodes API (because the relative-key → absolute-URL resolution at response time is the part the rest of the stack depends on), and the spoiler boundary in `test_retrieval.py` (the security-critical part of Post 6 — the tests prove the filter holds even against a jailbreak query that explicitly asks for future content), and the chat seams in `test_chat.py` (the suggestion-chip parser and the SSE event framing — the two places the streaming layer hides bugs).

### 9. Frontend: hand-rolled types, plain fetch, view-state by `useState`

`frontend/src/api/types.ts` mirrors the Pydantic response models in `backend/app/api/`. Keep them in sync by hand — the API surface is still small enough (~5 routes) that an `openapi-typescript` generator costs more than it pays. (Revisit if it crosses ~6 routes.) `frontend/src/api/client.ts` is plain `fetch` returning `Promise<T>`; the one exception is `streamMessage`, a hand-parsed Server-Sent-Events reader — the chat request is a `POST`, which the browser's `EventSource` can't do, so we read the response body as a stream and parse the `event:`/`data:` frames ourselves. Deferring to a query library is appropriate when caching, dedup, or focus-refetch start mattering, but isn't yet. The picker ↔ reader switch is a single `useState` in `App.tsx`; introduce `react-router-dom` only when deep links to a specific page become a real feature.

---

## Common commands

```bash
# Initial setup (one-time)
cp .env.example .env             # then edit values
docker compose up -d             # start Postgres + pgAdmin
cd backend && uv sync            # install Python deps
cd backend && uv run alembic upgrade head    # 11 rows in \dt

# Local model setup (one-time)
ollama pull qwen2.5:7b           # chat
ollama pull bge-m3               # embeddings

# Dev loops
cd backend && uv run uvicorn app.main:app --reload    # /health + episodes + sessions + chat (SSE) + /images
cd frontend && npm install && npm run dev             # http://localhost:5173 — reader + chat panel

# Type-check, lint, smoke-test
cd backend && uv run mypy app/   # Success: no issues found
cd backend && uv run ruff check app/  # All checks passed!
cd backend && uv run pytest -v   # 30 tests: storage + embeddings + episodes API + retrieval + chat
cd frontend && npm run type-check && npm run build    # tsc -b clean + Vite build

# Acquire one episode (used in Post 4 ingestion)
cd ingestion && uv run python acquire.py episode \
  --slug ep01_Potion-of-Flight --lang en --out ../data/raw

# Seed the canonical character roster
cd backend && uv run python -m app.db.seed    # 31 characters upserted

# Ingest the wiki seed (Post 7 — enables wiki mode + the wiki chip)
cd ingestion && uv run python ingest_wiki.py    # 5 articles → wiki_articles + wiki_v1

# Stream a chat answer over SSE (Post 7 — needs one ingested episode + backend running)
SID=$(curl -s -X POST localhost:8000/api/sessions -H 'content-type: application/json' \
  -d '{"episode_slug":"ep01-potion-of-flight"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')
curl -s -X PATCH localhost:8000/api/sessions/$SID -H 'content-type: application/json' \
  -d '{"current_page":3}'
curl -N -X POST localhost:8000/api/sessions/$SID/messages -H 'content-type: application/json' \
  -d '{"mode":"page","message":"who is on this page?"}'   # -N: unbuffered; watch token/done SSE frames
```

---

## Where to find things (this repo)

| Need to... | Look at |
|-----------|---------|
| Add a new model / storage provider | `backend/app/clients/` + the factory in `__init__.py` + `backend/app/config.py` |
| Change the spoiler filter / retrieval scope | `backend/app/retrieval/service.py` (`_spoiler_filter`) + `backend/tests/test_retrieval.py` |
| Change how an answer is assembled (context, prompt, model call) | `backend/app/orchestration/chat.py` + the prompt in `backend/app/core/prompts.py` |
| Change the streaming or the suggestion chips | `backend/app/orchestration/chat.py` (`stream_response`, `_generate_suggestions`, `_parse_suggestions`) + `SUGGESTIONS_SYSTEM`/`_SUGGESTIONS_SCHEMA` |
| Change the chat UI or the SSE consumer | `frontend/src/components/ChatPanel.tsx` + `streamMessage` in `frontend/src/api/client.ts` |
| Add or edit wiki content | `ingestion/wiki_seed.yaml`, then `cd ingestion && uv run python ingest_wiki.py` |
| Inspect the SQLAlchemy data model | `backend/app/db/models.py` |
| Read the field-by-field schema rationale | `docs/data-model.md` |
| Read the local-first / provider / storage rationale | `docs/decisions/0001`-`0003` |
| Change DB schema | `backend/app/db/models.py` + new Alembic migration via `uv run alembic revision --autogenerate -m "..."` |
| Verify the FastAPI scaffold boots | `uv run uvicorn app.main:app --reload`, then `curl http://localhost:8000/health` |
| Add or change an API route | `backend/app/api/` — Pydantic response models declared inline next to the router; resolve relative storage keys through `Storage.url_for()` in the handler |
| Add or change a frontend component | `frontend/src/components/` — keep components small, lift state to `App.tsx`. `frontend/src/api/types.ts` must mirror the Pydantic models by hand |
| Verify the frontend boots | `cd frontend && npm run dev`, open <http://localhost:5173> — relies on Vite's `/api` and `/images` proxy to the backend |

---

## Definition of done for any change

- [ ] Type-checks pass (`mypy --strict`)
- [ ] Lint passes (`ruff check`)
- [ ] Provider abstraction is honored — no SDK imports outside `clients/`
- [ ] If you added a database column, you wrote the migration
- [ ] `README.md` setup steps still work end-to-end (verify if you touched setup)

---

## Out of scope (do not build without asking)

- Authentication beyond an optional email gate
- Multi-user / multi-tenancy
- A full admin UI for managing episodes
- Real-time collaboration / shared sessions
- Mobile native apps
- Anything involving comics the project does not have a license to use

---

## Licensing & attribution

Pepper & Carrot is © David Revoy, licensed CC BY 4.0. Any UI built on top of downloaded comic content must visibly credit David Revoy and link to <https://www.peppercarrot.com>. Re-ingesting from peppercarrot.com is fine; redistributing the source files is fine under CC BY but credit must accompany them.

The code in this repository is MIT-licensed — see [`LICENSE`](LICENSE).

---

## Style notes for chat / prose *(active from Post 7)*

When the application generates user-facing text (chat responses, UI copy), prefer warm, conversational tone — Pepper & Carrot itself is warm and playful, and the companion should match. Avoid corporate AI-speak ("I'd be happy to help!"). The reader is exploring a witch's world; the companion can lean a little whimsical.
