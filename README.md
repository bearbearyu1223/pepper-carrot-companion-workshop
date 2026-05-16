# pepper-carrot-companion-workshop

Companion code for the first three posts of the **Pepper & Carrot AI-powered flipbook** series. This repository is the minimum working dev environment a reader needs to reproduce every verification step in the blog posts.

- **Post 1 — [When Your Chunks Are Comic Pages](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-trailer/)** *(series introduction; no code)*
- **Post 2 — [Setting Up the Workshop](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-workshop/)** *(Postgres, Ollama, FastAPI scaffold, first Alembic migration, one episode on disk)*
- **Post 3 — [Provider Abstractions](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-provider-abstractions/)** *(`Storage` / `EmbeddingClient` / `ChatClient` Protocols, the factory, a `LocalStorage` end-to-end loop, and `OllamaEmbeddingClient` + `SentenceTransformersEmbeddingClient` producing real 1024-dim vectors)*

Subsequent posts (Post 4 onwards — ingestion via Claude Skills, the RAG layer, the frontend flipbook, the world graph, the cloud deploy) build on top of this scaffold in a separate repository.

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
├── ingestion/
│   └── acquire.py              # downloads one episode from peppercarrot.com
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

### 8. (Optional) Seed the character roster

```bash
cd backend
uv run python -m app.db.seed
# 31 named characters upserted into `characters`
```

The seed is idempotent — re-run safely.

## A few things this repo intentionally does *not* include

- **Frontend / flipbook UI** (Post 5+ adds it).
- **API routers** beyond `/health` and `/images` (Post 5 wires episodes / pages, Post 6+ wires chat).
- **Chat orchestration & retrieval pipeline** (Post 6).
- **Claude Code skills** for page descriptions and the world graph (Posts 4 and 9).
- **Cloud deploy** (Modal / Fly / R2 / Neon) — Post 10.

Some of `pyproject.toml`'s dependencies (`chromadb`, `boto3`, `pillow`, `blurhash`) are listed because they're used by later phases. They install but aren't exercised by anything in this repo. The lockfile is committed so installs are byte-reproducible.

## Pepper & Carrot is © David Revoy

The webcomic itself is © [David Revoy](https://www.davidrevoy.com/) and licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). If you re-distribute downloaded content, you must credit David and link to <https://www.peppercarrot.com>. The MIT license in `LICENSE` covers the **code** in this repository only.

## License

[MIT](LICENSE)
