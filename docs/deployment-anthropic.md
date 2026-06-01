# Deployment — the managed-API path (Anthropic + Voyage, no GPU)

This is the **alternative** to [`docs/deployment.md`](deployment.md). The
default guide puts the AI layer on a Modal GPU because the series is *about*
local-first, self-hosted inference. This guide skips Modal entirely: chat runs
on the [Anthropic Messages API](https://docs.anthropic.com/en/api/messages),
embeddings run on the [Voyage AI API](https://docs.voyageai.com/reference/embeddings-api).
No GPU to operate, no cold start on the first answer, ~$0.10/mo for the chat
layer instead of ~$5–10. The narrative behind the choice is **Post 11**; the
why is [`docs/decisions/0005-managed-api-alternative.md`](decisions/0005-managed-api-alternative.md).

**Everything that isn't the AI layer is identical to the default path.** Neon,
R2, Fly, and Cloudflare Pages are set up exactly as in `deployment.md`. This
guide reproduces the AI-specific steps in full and points back to
`deployment.md` for the rest so the two don't drift.

## What you're building

Same five shapes as the default deploy — only the AI row changes:

| Piece | Service | What it does in plain English |
|---|---|---|
| **Frontend** (React + Vite UI) | Cloudflare Pages | Static CDN. Free. |
| **Backend** (FastAPI) | Fly.io | Runs your Python container, scale-to-zero. Free tier. |
| **Database** | Neon | Hosted Postgres, sleeps when idle. Free tier: 0.5 GB. |
| **Image storage** | Cloudflare R2 | S3-compatible bucket, no egress fees. Free first 10 GB. |
| **Chat model** | **Anthropic API** | `claude-haiku-4-5` answers each question. Pay per token. |
| **Embeddings** | **Voyage AI API** | `voyage-4-lite` turns each question into a query vector. Pay per token. |

**Total cost** at portfolio traffic: typically **under $1/mo** — the chat layer
is ~$0.10, everything else is free tier.

---

## Glossary

A few terms used throughout. Skip if you already know them.

- **Managed inference API** — instead of running a model on hardware you
  rent, you POST your prompt to a vendor's HTTPS endpoint and get the
  answer back. No GPU, no weights, no cold start from your side; you pay
  per token of input and output. Anthropic (chat) and Voyage (embeddings)
  are both this shape.

- **Embedding** — a list of numbers (a *vector*) that represents the
  meaning of a piece of text, so that "similar meaning" becomes "close in
  number-space." The chat layer embeds each question to find the most
  relevant page/wiki chunks via vector search. See [Post 6](https://bearbearyu1223.github.io/posts/pepper-carrot-companion-spoiler-safe-rag/).

- **Vector space** — the coordinate system an embedding model places its
  vectors in. **Two different embedders produce vectors in two different,
  incompatible spaces.** A `bge-m3` vector and a `voyage-4-lite` vector
  can't be compared to each other — which is why switching embedders means
  re-embedding everything (Step 2). This is the one real gotcha on this
  path.

- **Pooler / pooled endpoint** — Neon puts pgbouncer in front of the
  database. asyncpg (the backend's driver) doesn't get along with
  pgbouncer in transaction mode, so the backend uses the *unpooled*
  endpoint and the one-off `psql` restore uses the *pooled* one. (Same as
  the default path — see `deployment.md` for the long version.)

- **CORS** — the backend at `*.fly.dev` must explicitly trust requests
  from your frontend at `*.pages.dev`, via the `CORS_ORIGINS` env var.

---

## Prerequisites

1. **The app runs locally end-to-end.** You've followed `README.md` setup,
   ingested at least one episode, ingested the wiki, and verified the
   flipbook + chat work at `http://localhost:5173`.

2. **Accounts (all free to sign up):**
   - [Fly.io](https://fly.io) — backend host (requires a card).
   - [Neon](https://neon.tech) — Postgres.
   - [Cloudflare](https://dash.cloudflare.com) — Pages + R2.
   - [Anthropic Console](https://console.anthropic.com) — chat API. Pay-as-you-go; add a small credit balance.
   - [Voyage AI](https://dashboard.voyageai.com) — embeddings API. Free tier covers portfolio re-indexing comfortably.

   **No Modal account needed.**

3. **CLIs installed** (no `modal` this time):

   ```bash
   brew install flyctl rclone
   ```

4. **A `.env.production` file** from the Anthropic template:

   ```bash
   cp .env.production.anthropic.example .env.production
   ```

   This file is gitignored; you'll fill it in step-by-step below.

---

## Step 1 — Get the two API keys

1. **Anthropic.** [console.anthropic.com](https://console.anthropic.com) →
   **Settings → API Keys → Create Key**. Copy it (`sk-ant-…`) into
   `ANTHROPIC_API_KEY`. Add a few dollars of credit under **Billing** — at
   portfolio traffic you'll spend cents, but a $0 balance returns 400s.
   Leave `ANTHROPIC_MODEL=claude-haiku-4-5` unless you want to pay ~10× for
   `claude-sonnet-4-6` polish.

2. **Voyage.** [dashboard.voyageai.com](https://dashboard.voyageai.com) →
   **API Keys** → create one. Copy it (`pa-…`) into `VOYAGE_API_KEY`. Leave
   `VOYAGE_MODEL=voyage-4-lite`.

**Smoke-test both** before going further — a bad key here is invisible until
the first chat request fails in production:

```bash
set -a && source .env.production && set +a

# Anthropic — expect a JSON message with a short reply.
curl -sS https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"'"$ANTHROPIC_MODEL"'","max_tokens":16,"messages":[{"role":"user","content":"ping"}]}' \
  | python3 -m json.tool | head

# Voyage — expect {"data":[{"embedding":[...], "index":0}], ...}.
curl -sS https://api.voyageai.com/v1/embeddings \
  -H "Authorization: Bearer $VOYAGE_API_KEY" \
  -H "content-type: application/json" \
  -d '{"input":["ping"],"model":"'"$VOYAGE_MODEL"'"}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print("dim:", len(d["data"][0]["embedding"]))'
# dim: 1024   ← voyage-4-lite's default. NOTE: bge-m3 is ALSO 1024-dim, so this
#               number can't tell the two embedders apart — see the Step 2 warning.
```

---

## Step 2 — Re-index Chroma locally with Voyage embeddings

**This is the one step that has no analog in the default deploy, and the one
that bites if skipped.** Your local `data/chroma` holds `pages_v1` and
`wiki_v1`, both built with `bge-m3`. Voyage's vectors live in a *different
vector space*, so those collections are meaningless under the new embedder —
you must rebuild them.

> **The dimensionality is a red herring here.** Both `bge-m3` and
> `voyage-4-lite` default to **1024 dimensions**, so this is *not* a case where
> the wrong index is the wrong length — it's the right length and still wrong.
> Two embedding models lay text out in two different coordinate systems; a
> 1024-number vector from Voyage and a 1024-number vector from bge-m3 are not
> comparable just because they're both 1024 numbers long. (If you'd configured
> `voyage-4-lite` to emit 512-dim vectors via its Matryoshka output, the
> mismatch would *also* be a length mismatch — but matching lengths never make
> the spaces compatible.)

> **Why a redeploy can't fix this.** Chroma is baked into the Docker image at
> build time. If you ship a `bge-m3`-built Chroma against a Voyage runtime,
> retrieval *looks* like it works — it returns chunk IDs, the grounding text
> loads from Postgres — but the *ranking* is garbage, because the query vector
> (Voyage) and the stored vectors (bge-m3) aren't comparable. The chat answers
> from the model's general knowledge instead of the comic. Rebuild locally,
> then deploy.

Point your **local** `.env` at Voyage and rebuild:

```bash
# 1. Switch the local embedding provider. (Append to .env, or edit it.)
echo 'EMBEDDING_PROVIDER=voyage'      >> .env
echo 'VOYAGE_API_KEY=pa-...'          >> .env   # same key as Step 1
echo 'VOYAGE_MODEL=voyage-4-lite'     >> .env

# 2. Wipe the bge-m3 collections.
rm -rf data/chroma

# 3. Rebuild pages_v1 for EVERY ingested episode — no slug list to maintain.
#    Each episode lives in data/raw/ep*/ (the wiki dirs don't match `ep*`, so
#    they're skipped), and the wrapper maps a slug straight back to
#    data/raw/<slug> — so `basename` of each dir IS the slug it wants. The
#    page-description JSONs already exist on disk from your first ingest, so
#    nothing is re-described; only the embeddings (and Chroma) rebuild.
shopt -s nullglob                       # an empty glob expands to nothing, not a literal
for dir in data/raw/ep*/; do
  slug=$(basename "$dir")
  echo "── re-indexing $slug ──"
  .claude/skills/ingest-from-images/scripts/reingest_with_json.sh "$slug"
done

# 4. Rebuild wiki_v1 from the wiki summaries.
cd ingestion && uv run python ingest_wiki.py && cd ..
```

> **Why a loop over `data/raw/ep*/` and not a slug list?** The
> `reingest_with_json.sh <slug>` wrapper (the same one README Step 9 documents)
> resolves its argument to `data/raw/<slug>`, flips `VISION_PROVIDER=json` for
> the run, and calls `ingest.py --episode-dir …` against the existing JSONs —
> reverting `VISION_PROVIDER` on exit even if a run fails. Because the slug and
> the directory name are the same thing, iterating the directories and handing
> each `basename` back to the wrapper re-indexes exactly the episodes you
> ingested, with zero hard-coded slugs. Prefer to drive `ingest.py` yourself?
> The wrapper's one-liner is `cd ingestion && uv run python ingest.py
> --episode-dir ../data/raw/<slug>` — loop that over `../data/raw/ep*/` the same
> way (vision is always JSON-sourced in this starter, so the `VISION_PROVIDER`
> flip is belt-and-suspenders).

**Sanity-check that the rebuild produced a non-empty, well-formed index:**

```bash
cd backend && uv run python -c "
import chromadb
c = chromadb.PersistentClient(path='../data/chroma')
for name in ('pages_v1', 'wiki_v1'):
    col = c.get_collection(name)
    got = col.get(limit=1, include=['embeddings'])   # get() needs an explicit include
    embs = got['embeddings']
    dim = len(embs[0]) if embs is not None and len(embs) else 0
    print(f'{name}: {col.count()} chunks, dim={dim}')
"
# pages_v1: N chunks, dim=1024
# wiki_v1:  M chunks, dim=1024
```

Non-zero counts and `dim=1024` confirm the rebuild ran and stored valid
vectors. **But `dim=1024` does *not* prove the index is in Voyage's space** —
`bge-m3` is also 1024-dim, so this number looks identical either way. Two
things give you real confidence the index is Voyage's:

1. **The rebuild can't succeed under the wrong embedder.** You set
   `EMBEDDING_PROVIDER=voyage` and wiped `data/chroma` first, and the
   ingestion factory raises if `VOYAGE_API_KEY` is missing — so a rebuild that
   *completed* did so by calling Voyage. (If the provider hadn't switched, you'd
   either get a `sentence-transformers`/Ollama rebuild or a loud error, not a
   silent bge-m3 one.)
2. **The functional check below is authoritative.** A grounded answer is the
   only proof that query-space and index-space agree.

**Functional check — embed a query the same way retrieval will, and confirm the
nearest chunk is sensible:**

```bash
cd backend && uv run python -c "
import asyncio, chromadb
from app.config import get_settings
from app.clients import get_embedding_client
settings = get_settings()                       # reads EMBEDDING_PROVIDER=voyage from .env
client = get_embedding_client(settings)
q = 'Who is Pepper and where does she live?'
vec = asyncio.run(client.embed_batch([q]))[0]   # a Voyage query vector
col = chromadb.PersistentClient(path='../data/chroma').get_collection('wiki_v1')
hit = col.query(query_embeddings=[vec], n_results=1, include=['documents'])
print(hit['documents'][0][0][:200])
"
# Want: a Pepper/Hereva wiki snippet. Gibberish or an unrelated entity means
# the query embedder and the stored vectors disagree — re-check Step 2.
```

If the snippet is on-topic, query-space and index-space match and you're clear
to deploy. If it's unrelated, the index wasn't rebuilt under Voyage — re-run
from `rm -rf data/chroma` with `EMBEDDING_PROVIDER=voyage` confirmed in `.env`.

> **Postgres and R2 stay put.** The canonical page/wiki text lives in Postgres
> and the image bytes live in R2 — neither depends on the embedder. Only Chroma
> rebuilds. You'll still dump the seed in Step 5 (it captures the same Postgres
> rows), and you do **not** need to re-upload images to R2.

---

## Step 3 — Provision Neon (Postgres)

**Identical to the default path.** Follow
[`docs/deployment.md` Step 2](deployment.md#step-2--provision-neon-postgres)
end to end: create the project, copy the **pooled** URL into
`POSTGRES_RESTORE_URL` and the **unpooled** URL (with the
`postgresql+asyncpg://` scheme) into `DATABASE_URL_OVERRIDE`. The
asyncpg-vs-pgbouncer caveat is the same; nothing about Postgres is coupled to
the chat layer.

---

## Step 4 — Provision Cloudflare R2 (image storage)

**Identical to the default path.** Follow
[`docs/deployment.md` Step 3](deployment.md#step-3--provision-cloudflare-r2-image-storage):
create the bucket, mint an Object-Read-&-Write token, enable public access,
configure rclone, scrub `.DS_Store`, and `rclone copy` the images up. Paste the
four R2 values plus `R2_BUCKET` and `R2_PUBLIC_URL_PREFIX` into
`.env.production`. Image storage doesn't know or care which model answers the
chat.

---

## Step 5 — Dump the Postgres seed

**Identical to the default path** ([`docs/deployment.md` Step 4](deployment.md#step-4--dump-the-postgres-seed)):

```bash
./infra/dump_seed.sh
```

This writes `data/seed.sql` (gitignored), which the Docker build bakes in and
Fly's `release_command` restores into a fresh Neon DB on first boot. Re-run it
whenever your local Postgres changes. The seed captures the same `episodes` /
`pages` / `wiki_articles` rows regardless of embedder — your Step 2 re-index
changed Chroma, not Postgres, so the seed is unchanged in content but should be
re-dumped if you've ingested any new episodes.

---

## Step 6 — Deploy the backend (Fly.io)

Two differences from the default path, both about the provider env vars.

### 6a — Flip the providers in `fly.toml`

The committed `fly.toml` carries an `[env]` block tuned for the **default**
(Modal) path:

```toml
[env]
  CHAT_PROVIDER = 'ollama'
  EMBEDDING_MODEL = 'bge-m3'
  EMBEDDING_PROVIDER = 'ollama'
  LOG_LEVEL = 'INFO'
  OLLAMA_CHAT_MODEL = 'qwen2.5:7b'
  STORAGE_BACKEND = 'r2'
```

Edit it for this path — flip the two providers, drop the Ollama-only model
vars (they're harmless if left, but cleaner gone):

```toml
[env]
  CHAT_PROVIDER = 'anthropic'
  EMBEDDING_PROVIDER = 'voyage'
  LOG_LEVEL = 'INFO'
  STORAGE_BACKEND = 'r2'
```

> **Why edit `fly.toml` instead of setting these as secrets?** `CHAT_PROVIDER`
> and `EMBEDDING_PROVIDER` aren't secrets — they're config, and config belongs
> in version-controlled `fly.toml`. (Fly secrets *do* override `[env]` values
> of the same name, so `fly secrets set CHAT_PROVIDER=anthropic` would also
> work — but then the provider choice lives invisibly in your Fly account
> instead of in the repo. Keep secrets for the API keys only.)

### 6b — Launch, push the API-key secrets, deploy

```bash
fly auth login
fly launch --no-deploy --copy-config        # reuses the edited fly.toml
```

Push the secrets — the **API keys and the connection/CORS values**, not the
providers (those are now in `fly.toml`):

```bash
set -a && source .env.production && set +a && \
fly secrets set \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  ANTHROPIC_MODEL="$ANTHROPIC_MODEL" \
  VOYAGE_API_KEY="$VOYAGE_API_KEY" \
  VOYAGE_MODEL="$VOYAGE_MODEL" \
  DATABASE_URL_OVERRIDE="$DATABASE_URL_OVERRIDE" \
  POSTGRES_RESTORE_URL="$POSTGRES_RESTORE_URL" \
  R2_ACCOUNT_ID="$R2_ACCOUNT_ID" \
  R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
  R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  R2_BUCKET="$R2_BUCKET" \
  R2_PUBLIC_URL_PREFIX="$R2_PUBLIC_URL_PREFIX" \
  CORS_ORIGINS="$CORS_ORIGINS"
```

Then deploy (chain the seed dump so the image always has a fresh `seed.sql`):

```bash
./infra/dump_seed.sh && fly deploy
```

The build bakes your **Voyage-built** `data/chroma` into the image — which is
why Step 2 had to happen first. On first boot the `release_command` restores
`seed.sql` into the empty Neon DB, then the app machine boots and `exec`s
uvicorn.

**Verify:**

```bash
curl https://pepper-carrot-ai-flipbook-workshop.fly.dev/health
# {"status":"ok"}
curl -s https://pepper-carrot-ai-flipbook-workshop.fly.dev/api/episodes | head -c 300
# JSON array of episode metadata with absolute R2 cover URLs
```

---

## Step 7 — Deploy the frontend (Cloudflare Pages)

**Identical to the default path** ([`docs/deployment.md` Step 6](deployment.md#step-6--deploy-the-frontend-cloudflare-pages)):
connect the repo, set the build command to
`cd frontend && npm install && npm run build`, output dir `frontend/dist`, and
`VITE_API_BASE_URL=https://pepper-carrot-ai-flipbook-workshop.fly.dev`. After
Pages prints its `*.pages.dev` URL, set `CORS_ORIGINS` on Fly to match it
exactly:

```bash
fly secrets set CORS_ORIGINS='["https://your-app.pages.dev"]'
```

---

## Step 8 — End-to-end test

Open the Pages URL. The flow is the same as the default path — with **one happy
difference**: the first chat answer is *fast*. There's no Modal GPU to
cold-start, so the only first-request latency is Fly's wake-from-zero (~5–10 s)
if the backend was idle, and then Anthropic streams immediately.

```bash
# Terminal check — the actual user flow, end to end.
SID=$(curl -s -X POST https://pepper-carrot-ai-flipbook-workshop.fly.dev/api/sessions \
  -H 'content-type: application/json' \
  -d '{"episode_slug":"ep01-potion-of-flight"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')
curl -s -X PATCH "https://pepper-carrot-ai-flipbook-workshop.fly.dev/api/sessions/$SID" \
  -H 'content-type: application/json' -d '{"current_page":1}'
curl -N -X POST "https://pepper-carrot-ai-flipbook-workshop.fly.dev/api/sessions/$SID/messages" \
  -H 'content-type: application/json' \
  -d '{"mode":"page","message":"who is on this page?"}'
# Want: a token stream → coherent, grounded answer → a `done` SSE frame with
# retrieved_doc_ids and two suggestion chips. No 15–30s pause.
```

If chat answers from the comic (not from general knowledge), the Voyage
re-index from Step 2 took. If it answers generically while `retrieved_doc_ids`
is **non-empty**, you almost certainly deployed a stale (bge-m3) Chroma — redo
Step 2, then `fly deploy`.

---

## Troubleshooting

These supplement the default guide's
[troubleshooting table](deployment.md#troubleshooting) — every Neon / R2 / Fly /
CORS row there applies unchanged. The rows below are specific to this path.

| Symptom | Likely cause | Fix |
|---|---|---|
| Chat 401 / `authentication_error` in `fly logs` | `ANTHROPIC_API_KEY` wrong or unset | `fly secrets set ANTHROPIC_API_KEY=sk-ant-…`. Confirm with the Step 1 curl. |
| Chat 400 `credit balance is too low` | Anthropic account has $0 balance | Add credit under console.anthropic.com → Billing. |
| Embeddings fail, `fly logs` shows a Voyage 401 | `VOYAGE_API_KEY` wrong or unset | `fly secrets set VOYAGE_API_KEY=pa-…`. Confirm with the Step 1 curl. |
| Chat answers from general knowledge, `done` frame has **non-empty** `retrieved_doc_ids` | Deployed a `bge-m3`-built Chroma against a Voyage runtime — query vector and stored vectors are in different spaces, so ranking is meaningless. (Both are 1024-dim, so it won't *look* wrong.) | Redo Step 2 (`rm -rf data/chroma`, re-ingest with `EMBEDDING_PROVIDER=voyage`), pass the Step 2 functional check, then `fly deploy`. |
| Chat answers from general knowledge, `done` frame has **empty** `retrieved_doc_ids` | Baked Chroma is empty — Step 2 wiped it but the re-ingest didn't run, or `fly deploy` baked before the rebuild | Confirm local counts > 0 (the Step 2 sanity snippet), then re-bake with `fly deploy`. |
| `fly logs` shows `Unknown embedding_provider` or `Unknown chat_provider` | `fly.toml` `[env]` still says `ollama`, and no secret overrides it | Edit `fly.toml` per Step 6a (or `fly secrets set CHAT_PROVIDER=anthropic EMBEDDING_PROVIDER=voyage`). |
| Retrieval ranks badly after changing `VOYAGE_MODEL` (e.g. trying a 512-dim Matryoshka output) | The baked `pages_v1`/`wiki_v1` were built at one output dimension but the runtime embeds at another, or in a different model's space | Keep `VOYAGE_MODEL` (and any output-dimension setting) **identical** between the local re-index and the Fly deploy. Re-index whenever you change it. |

If you hit something not here, `fly logs --no-tail | tail -50` usually names the
failing field in its last few lines.
