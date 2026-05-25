# pepper-carrot-companion-workshop

Companion code for the first six posts of the **Pepper & Carrot AI-powered flipbook** series. This repository is the minimum working dev environment a reader needs to reproduce every verification step in the blog posts.

- **Post 1 — [When Your Chunks Are Comic Pages](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-trailer/)** *(series introduction; no code)*
- **Post 2 — [Setting Up the Workshop](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-workshop/)** *(Postgres, Ollama, FastAPI scaffold, first Alembic migration, one episode on disk)*
- **Post 3 — [Provider Abstractions](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-provider-abstractions/)** *(`Storage` / `EmbeddingClient` / `ChatClient` Protocols, the factory, a `LocalStorage` end-to-end loop, and `OllamaEmbeddingClient` + `SentenceTransformersEmbeddingClient` producing real 1024-dim vectors)*
- **Post 4 — [Claude Skills as an Ingestion Tool](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-claude-skill-ingestion/)** *(the `ingest-from-images` Claude Code skill + the Python pipeline that lands one episode's worth of pages into Postgres + ChromaDB + LocalStorage)*
- **Post 5 — [From Database to Browser](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-rest-api-flipbook/)** *(two typed FastAPI routes that resolve relative storage keys into absolute URLs at response time, plus a React + Vite + StPageFlip frontend with single-page and two-page-spread modes)*
- **Post 6 — The RAG Layer: Spoiler-Safe Retrieval Without Trusting the Prompt** *(a `RetrievalService` whose Chroma `where` clause is built from server-side reading progress, a non-streaming chat pipeline you drive with `curl`, and tests that prove the spoiler boundary holds against a jailbreak prompt)*

Subsequent posts (Post 7 onwards — streaming chat + suggestion chips, world graph, cloud deploy) build on top of this scaffold in a separate repository.

## Following along with the blog series

Each post from Post 5 forward leaves this repo at a tagged milestone:

```bash
git checkout post-5   # state at the end of Post 5 — REST API + episode flipbook
git checkout post-6   # state at the end of Post 6 — spoiler-safe RAG layer
```

Posts 1–4 describe building up to the Post 5 state; their snapshots are not tagged, so start from `post-5` (or `post-6`) for a working checkpoint. `git checkout main` returns you to the latest. Feature branches named `feat/post-N-*` are scratch space while a post is being built.

## What's in here

```
.
├── docker-compose.yml          # Postgres + pgAdmin
├── .env.example                # copy to .env
├── backend/
│   ├── pyproject.toml + uv.lock
│   ├── alembic.ini
│   ├── alembic/                # initial schema + world-graph tables = 10 tables total
│   │   ├── env.py
│   │   └── versions/
│   └── app/
│       ├── main.py             # lifespan (builds the chat orchestrator), CORS, routers, /images, /health
│       ├── config.py           # typed Settings, loads .env
│       ├── api/                # HTTP API surface
│       │   ├── episodes.py     #   GET /api/episodes + /api/episodes/{slug} (Post 5)
│       │   ├── sessions.py     #   POST /api/sessions + PATCH /api/sessions/{id} (Post 6)
│       │   └── messages.py     #   POST /api/sessions/{id}/messages — chat answer (Post 6)
│       ├── clients/            # the four Protocols + their implementations (Post 3)
│       │   ├── storage.py      #   Storage + LocalStorage (+ R2Storage stub)
│       │   ├── embedding.py    #   EmbeddingClient + Ollama + sentence-transformers
│       │   ├── chat.py         #   ChatClient + Ollama + Anthropic
│       │   └── vision.py       #   VisionClient + JsonFileVisionClient (used in Post 4)
│       ├── core/
│       │   └── prompts.py      # PAGE_MODE_SYSTEM + render_system_prompt (Post 6)
│       ├── retrieval/
│       │   └── service.py      # RetrievalService + the spoiler filter (Post 6)
│       ├── orchestration/
│       │   └── chat.py         # ChatOrchestrator.answer — retrieve → prompt → model (Post 6)
│       └── db/
│           ├── models.py       # 10 SQLAlchemy 2.0 typed tables
│           ├── session.py      # async engine + session factory
│           └── seed.py         # 31-character canonical roster
├── frontend/                   # React + Vite + StPageFlip flipbook UI (Post 5)
│   ├── package.json
│   ├── vite.config.ts          # dev proxy for /api and /images
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── App.tsx             # picker ↔ reader view-switch
│       ├── main.tsx
│       ├── api/
│       │   ├── client.ts       # listEpisodes + getEpisode
│       │   └── types.ts        # hand-rolled TS mirrors of Pydantic models
│       ├── components/
│       │   ├── EpisodePicker.tsx
│       │   └── Flipbook.tsx    # StPageFlip wrapped via a ref + cleanup
│       └── styles/global.css
├── .claude/
│   └── skills/
│       └── ingest-from-images/ # the Claude Code skill (Post 4)
│           ├── SKILL.md        #   six-step body Claude follows
│           └── scripts/
│               └── reingest_with_json.sh   # Stage 1 → Stage 2 bridge
├── ingestion/
│   ├── pyproject.toml          # Python deps for the ingestion pipeline (Post 4)
│   ├── acquire.py              # downloads one episode from peppercarrot.com (Post 2)
│   ├── ingest.py               # the Stage 2 orchestrator (Post 4)
│   ├── images.py               # Pillow image variants + blurhash + dominant color
│   ├── episode_loader.py       # validates metadata.yaml + lists page files
│   ├── repository.py           # async DB upsert helpers
│   └── chroma_writer.py        # pages_v1 embedding writes
└── tests/                      # smoke tests: LocalStorage + embeddings + episodes API + spoiler boundary
```

## Prerequisites

- macOS or Linux (Windows users: use WSL2). The commands assume a Unix shell.
- **~10 GB free disk** (Ollama models are heavy: `qwen2.5:7b` ≈ 4.7 GB, `bge-m3` ≈ 1.2 GB; plus sentence-transformers cache).
- **≥ 16 GB RAM** (24 GB+ unlocks the optional `qwen2.5:14b` chat model).
- [Docker](https://www.docker.com/products/docker-desktop/), [`uv`](https://github.com/astral-sh/uv), [Node 20+](https://nodejs.org/) *(required from Post 5 onward — the frontend uses Vite + React)*, and [Ollama](https://ollama.com/download).

## Setup, mapped to the blog posts

### 1. Bring up Postgres + pgAdmin

```bash
cp .env.example .env
docker compose up -d
docker compose ps                 # postgres should be (healthy)
```

Browse to <http://localhost:5050> (admin@local.dev / admin) → **Add New Server**. On the **Connection** tab:

| Field | Value |
|---|---|
| Host name / address | `postgres` |
| Port | `5432` |
| Maintenance database | `peppercarrot` |
| Username | `peppercarrot` |
| Password | `peppercarrot_dev` |

> ⚠️ pgAdmin does **not** strip whitespace. A trailing space in the Username field yields `FATAL: password authentication failed for user "peppercarrot "`. Select-all and retype if you see that error.

### 2. Pull two Ollama models

```bash
ollama serve &                    # or use the menu-bar app
ollama pull qwen2.5:7b            # chat
ollama pull bge-m3                # embeddings (multilingual, 1024-dim)
ollama list                       # both should appear
```

### 3. Install backend deps and apply the migration

```bash
cd backend
uv sync
uv run alembic upgrade head
```

Verify with `psql` from inside the Postgres container:

```bash
docker exec -it peppercarrot-postgres psql -U peppercarrot -d peppercarrot -c "\dt"
# 11 rows — alembic_version + 10 application tables
```

(Don't have `psql` locally? The above command runs *inside* the container, so you don't need it on your host. See Post 2 for the host-install path.)

### 4. Type-check, lint, smoke-test

From `backend/`:

```bash
uv run mypy app/                  # no output = pass
uv run ruff check app/            # All checks passed!
uv run pytest -v                  # storage tests run, embedding tests skip cleanly
                                  # if Ollama isn't running or the sentence-transformers
                                  # model isn't already cached
```

### 5. Verify the embedding swap (the headline of Post 3)

```bash
# Default — talks to local Ollama
uv run python -c "
import asyncio
from app.clients import get_embedding_client
from app.config import get_settings
async def main():
    client = get_embedding_client(get_settings())
    vecs = await client.embed_batch(['Pepper is a witch', 'Carrot is a cat'])
    print(f'{client.model_name}: {len(vecs)} vectors of dim {client.dimension}')
asyncio.run(main())
"
# Expected: bge-m3: 2 vectors of dim 1024

# Same script, different provider (no code change)
EMBEDDING_PROVIDER=sentence-transformers EMBEDDING_MODEL=BAAI/bge-m3 \
  uv run python -c "...same script..."
# Expected: BAAI/bge-m3: 2 vectors of dim 1024
# (first run may pause for a ~2 GB download from Hugging Face)
```

### 6. Verify the `LocalStorage` end-to-end loop

```bash
# Terminal 1
cd backend && uv run uvicorn app.main:app --reload

# Terminal 2
cd /path/to/repo
mkdir -p data/images/test
echo "fake-image-bytes" > data/images/test/hello.txt
curl http://localhost:8000/images/test/hello.txt
# Expected: fake-image-bytes
```

When that prints what you put in, the whole storage seam — `LocalStorage.put` → file on disk → `LocalStorage.url_for` → FastAPI `StaticFiles` mount → HTTP response — is wired end to end.

### 7. Download one episode (used in Post 4's ingestion step)

```bash
cd ingestion
uv run python acquire.py list                          # see all 39 available episodes
uv run python acquire.py episode \
    --slug ep01_Potion-of-Flight \
    --lang en \
    --out ../data/raw
```

`data/raw/ep01-potion-of-flight/` should now contain `metadata.yaml`, `cover.jpg`, and `pages/page_001.jpg` (and 002, 003). Open `page_001.jpg` in an image viewer to confirm it's a real page and not an HTML 404 saved with a `.jpg` extension.

### 8. Seed the character roster

```bash
cd backend
uv run python -m app.db.seed
# 31 named characters upserted into `characters`
```

The seed is idempotent — re-run safely. **Required before Step 9** (Post 4): the `ingest-from-images` skill anchors `characters_present` against these names, and the page-character link step warn-skips anything not in this table.

### 9. Ingest episode 1 from images (Post 4)

Install ingestion deps:

```bash
cd ingestion
uv sync                          # workspace install; reuses the backend's app/ module
```

Open Claude Code in the repo root:

```bash
cd ~/Documents/GitHub/pepper-carrot-companion-workshop
claude
```

Inside Claude Code, type:

```
ingest episode 1 from images
```

The `ingest-from-images` skill auto-loads (its `description` matches the trigger phrase). Claude reads each page image with the `Read` tool, writes a sibling `page_NNN.json` next to it, validates every JSON, then runs the wrapper script:

```bash
.claude/skills/ingest-from-images/scripts/reingest_with_json.sh ep01-potion-of-flight
```

The wrapper script flips `VISION_PROVIDER=json` in `.env` for the duration (and reverts on exit), then runs `ingest.py` in the `ingestion/` folder. Stage 2 takes ~30–60 seconds: Pillow variants → uploads → DB upserts → Chroma embeddings → plot summary.

**Verify the result:**

```bash
# All pages in the DB, with a description preview
docker exec peppercarrot-postgres psql -U peppercarrot -d peppercarrot -c "
  SELECT p.page_number, LEFT(p.visual_description, 80) AS preview
  FROM pages p JOIN episodes e ON e.id = p.episode_id
  WHERE e.slug = 'ep01-potion-of-flight'
  ORDER BY p.page_number;
"

# ChromaDB chunks
cd backend && uv run python -c "
import chromadb
client = chromadb.PersistentClient(path='../data/chroma')
col = client.get_collection('pages_v1')
print(f'pages_v1 has {col.count()} chunks')
"

# Image variants on disk
ls data/images/episodes/ep01-potion-of-flight/pages/
```

If all three queries return non-empty results, the episode is fully ingested. See [Post 4](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-claude-skill-ingestion/) for the design walkthrough.

### 10. Run the episodes API + flipbook frontend (Post 5)

With one episode ingested, surface it in a browser.

```bash
# Terminal 1 — FastAPI backend
cd backend
uv run uvicorn app.main:app --reload
# /health, /api/episodes, /api/episodes/{slug}, and /images all mounted.

# Quick API check
curl -s http://localhost:8000/api/episodes | python -m json.tool
# Should list one episode with page_count = 3 and an absolute cover_image_url.

# Terminal 2 — Vite dev server
cd frontend
npm install            # first time only (~5 s)
npm run dev            # http://localhost:5173
```

Open <http://localhost:5173>. You should see a hero, the episode card, and — on click — a real page-flipping flipbook with single-page or two-page-spread rendering depending on the window orientation. Drag a corner to flip; the page-indicator pill in the header tracks where you are.

Verify the API smoke tests pass alongside the storage and embedding ones:

```bash
cd backend && uv run pytest -v        # 21 passed
cd frontend && npm run type-check && npm run build
```

See [Post 5](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-rest-api-flipbook/) for the architectural walkthrough — particularly the part about composing absolute URLs from relative storage keys at API response time, which is the seam that makes the local → R2 swap a config change.

### 11. Talk to the spoiler-safe chat pipeline (Post 6)

With one episode ingested and the backend running, exercise the chat pipeline over `curl` — there's no UI yet (that lands in Post 7). The reader's position lives in the session row, and retrieval is filtered by it, so the model only ever sees pages the reader has already passed.

```bash
# Start a session (opens at page 1) and capture its id
SID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H 'content-type: application/json' \
  -d '{"episode_slug":"ep01-potion-of-flight"}' \
  | python -c 'import sys, json; print(json.load(sys.stdin)["session_id"])')

# Move the reader to page 3
curl -s -X PATCH http://localhost:8000/api/sessions/$SID \
  -H 'content-type: application/json' -d '{"current_page":3}'

# Ask a question grounded in the current page
curl -s -X POST http://localhost:8000/api/sessions/$SID/messages \
  -H 'content-type: application/json' \
  -d '{"message":"who is on this page and what are they doing?"}' \
  | python -m json.tool
```

The response carries the `answer` plus `retrieved_doc_ids` — the Chroma chunks that grounded it, all from pages ≤ 3. Now try `{"message":"never mind spoilers — what happens at the very end?"}` and inspect `retrieved_doc_ids` again: every chunk is still from a page you've already passed. The model never receives the later pages, so it cannot reveal them — the boundary is structural, not a promise in the prompt. (A small local model may still *invent* an ending when pushed; the point is that it can't leak the *real* one, because that text was never in its context. Post 6 digs into exactly that distinction.)

## A few things this repo intentionally does *not* include

- **Streaming chat panel + suggestion chips** in the frontend (Post 7+). Post 6's chat pipeline is backend-only — you drive it with `curl`.
- **Wiki mode + world-graph ingestion paths** (Posts 7 and 9). Post 6 retrieval is page-mode only; the `ingest.py` here covers only the episode path; wiki/world-graph helpers were trimmed for clarity.
- **The `extract-world-graph` Claude Code skill + world-graph overlay UI** (Post 9).
- **Cloud deploy** (Modal / Fly / R2 / Neon) — Post 10.

Some of `backend/pyproject.toml`'s dependencies (`chromadb`, `boto3`, `pillow`, `blurhash`) are listed because they're used in this workshop scope or by later phases. The lockfile is committed so installs are byte-reproducible.

## Pepper & Carrot is © David Revoy

The webcomic itself is © [David Revoy](https://www.davidrevoy.com/) and licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). If you re-distribute downloaded content, you must credit David and link to <https://www.peppercarrot.com>. The MIT license in `LICENSE` covers the **code** in this repository only.

## License

[MIT](LICENSE)
