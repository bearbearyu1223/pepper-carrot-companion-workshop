# pepper-carrot-companion-workshop

Companion code for the first four posts of the **Pepper & Carrot AI-powered flipbook** series. This repository is the minimum working dev environment a reader needs to reproduce every verification step in the blog posts.

- **Post 1 — [When Your Chunks Are Comic Pages](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-trailer/)** *(series introduction; no code)*
- **Post 2 — [Setting Up the Workshop](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-workshop/)** *(Postgres, Ollama, FastAPI scaffold, first Alembic migration, one episode on disk)*
- **Post 3 — [Provider Abstractions](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-provider-abstractions/)** *(`Storage` / `EmbeddingClient` / `ChatClient` Protocols, the factory, a `LocalStorage` end-to-end loop, and `OllamaEmbeddingClient` + `SentenceTransformersEmbeddingClient` producing real 1024-dim vectors)*
- **Post 4 — [Claude Skills as an Ingestion Tool](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-claude-skill-ingestion/)** *(the `ingest-from-images` Claude Code skill + the Python pipeline that lands one episode's worth of pages into Postgres + ChromaDB + LocalStorage)*

Subsequent posts (Post 5 onwards — REST API, frontend flipbook, RAG layer, world graph, cloud deploy) build on top of this scaffold in a separate repository.

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
│       ├── main.py             # /health + /images StaticFiles
│       ├── config.py           # typed Settings, loads .env
│       ├── clients/            # the four Protocols + their implementations (Post 3)
│       │   ├── storage.py      #   Storage + LocalStorage (+ R2Storage stub)
│       │   ├── embedding.py    #   EmbeddingClient + Ollama + sentence-transformers
│       │   ├── chat.py         #   ChatClient + Ollama + Anthropic
│       │   └── vision.py       #   VisionClient + JsonFileVisionClient (used in Post 4)
│       └── db/
│           ├── models.py       # 10 SQLAlchemy 2.0 typed tables
│           ├── session.py      # async engine + session factory
│           └── seed.py         # 31-character canonical roster
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
└── tests/                      # smoke tests for LocalStorage + both embedding clients
```

## Prerequisites

- macOS or Linux (Windows users: use WSL2). The commands assume a Unix shell.
- **~10 GB free disk** (Ollama models are heavy: `qwen2.5:7b` ≈ 4.7 GB, `bge-m3` ≈ 1.2 GB; plus sentence-transformers cache).
- **≥ 16 GB RAM** (24 GB+ unlocks the optional `qwen2.5:14b` chat model).
- [Docker](https://www.docker.com/products/docker-desktop/), [`uv`](https://github.com/astral-sh/uv), [Node 20+](https://nodejs.org/) *(only needed for later posts)*, and [Ollama](https://ollama.com/download).

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

## A few things this repo intentionally does *not* include

- **Frontend / flipbook UI** (Post 5+ adds it).
- **API routers** beyond `/health` and `/images` (Post 5 wires episodes / pages, Post 6+ wires chat).
- **Chat orchestration & retrieval pipeline** (Post 6+).
- **Wiki + world-graph ingestion paths** (Posts 6 and 9). The `ingest.py` here covers only the episode path; wiki/world-graph helpers were trimmed for clarity.
- **The `extract-world-graph` Claude Code skill** (Post 9).
- **Cloud deploy** (Modal / Fly / R2 / Neon) — Post 10.

Some of `backend/pyproject.toml`'s dependencies (`chromadb`, `boto3`, `pillow`, `blurhash`) are listed because they're used in this workshop scope or by later phases. The lockfile is committed so installs are byte-reproducible.

## Pepper & Carrot is © David Revoy

The webcomic itself is © [David Revoy](https://www.davidrevoy.com/) and licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). If you re-distribute downloaded content, you must credit David and link to <https://www.peppercarrot.com>. The MIT license in `LICENSE` covers the **code** in this repository only.

## License

[MIT](LICENSE)
