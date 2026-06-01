# Deployment

End-to-end guide for taking the local-first app from Posts 2–9 and putting
it on the public internet — for free or close to it. This document is the
operational reference; the narrative behind the choices is **Post 10** on
the blog.

## What you're building

Five pieces, each on a different free-or-cheap service:

| Piece | Service | What it does in plain English |
|---|---|---|
| **Frontend** (React + Vite UI) | Cloudflare Pages | Static CDN. Pages takes your built JS/CSS/HTML and serves it from edge nodes. Free. |
| **Backend** (FastAPI) | Fly.io | Runs your Python container. Sleeps when nobody's using it, wakes on the next request. Free up to a small monthly resource cap. |
| **Database** | Neon | Hosted PostgreSQL. Sleeps when idle, wakes on demand. Free tier: 0.5 GB. |
| **Image storage** | Cloudflare R2 | An S3-compatible bucket for the comic page images and world-graph avatars. Free for the first 10 GB, no bandwidth fees. |
| **AI models** (Ollama → qwen2.5:7b + bge-m3) | Modal | Serverless GPU. Spins up a GPU when a request comes in, charges by the second, shuts down when idle. ~$5–10/mo at portfolio traffic. |

**Total cost** at portfolio traffic: typically **$5–15/mo**, almost all
of it Modal GPU seconds. Everything else stays on free tiers.

---

## Glossary

A few terms used throughout. Skip if you already know them.

- **Cold start** — the time between a request arriving and the service
  being ready to answer. For Modal that means *allocating a GPU + loading
  the model weights into VRAM* (~15–25s for qwen2.5:7b after the first
  deploy; the first deploy is longer because it pulls the weights). For
  Fly it's *booting a Firecracker VM* (~5–10s). Opposite of **warm**:
  machine already running, next request is instant.

- **Scale-to-zero** — when a service is idle, the provider shuts the
  machine down so you stop paying. The next request triggers a cold
  start. Trade-off: "$0 idle, slow first request" vs. "always warm,
  costs more."

- **Serverless GPU** — Modal's model: you don't rent a GPU by the hour,
  you hand them a container and they allocate a GPU only when a request
  needs one. Pay for active seconds plus a short idle window.

- **Proxy auth (Modal)** — Modal can require a `Modal-Key` /
  `Modal-Secret` header pair on every request to your endpoint. Without
  it, the URL is the only secret — fine for staging, risky for a public
  portfolio (anyone who finds it can run up the bill).

- **Pooler / pooled endpoint** — Neon puts a process called pgbouncer in
  front of the database to multiplex connections. asyncpg (the driver
  the backend uses) doesn't get along with pgbouncer in transaction
  mode, so we use the *unpooled* endpoint for the backend and the
  *pooled* endpoint only for the one-off `psql` restore.

- **CORS** — when your frontend at `your-app.pages.dev` calls your
  backend at `your-app.fly.dev`, that's a cross-origin request. The
  browser blocks it unless the backend explicitly says "I trust requests
  from `your-app.pages.dev`." That's the `CORS_ORIGINS` env var.

---

## Prerequisites

1. **The app runs locally end-to-end.** You've followed `README.md`
   setup, ingested at least one episode, and verified the flipbook +
   chat work at `http://localhost:5173`.

2. **Accounts (all free to sign up):**
   - [Fly.io](https://fly.io) — backend host. Add a payment method
     during sign-up; the free tier covers a sleepy demo but Fly requires
     a card.
   - [Neon](https://neon.tech) — Postgres.
   - [Cloudflare](https://dash.cloudflare.com) — Pages + R2 (one
     account, both products).
   - [Modal](https://modal.com) — GPU host.

3. **CLIs installed:**

   ```bash
   brew install flyctl rclone
   uv tool install modal       # or: brew install pipx && pipx install modal
   ```

4. **A `.env.production` file** with the values you'll set on each
   service. Copy the template:

   ```bash
   cp .env.production.example .env.production
   ```

   This file is gitignored; you'll fill it in step-by-step below.

---

## Step 1 — Deploy Ollama on Modal

```bash
modal token new                         # one-time browser auth
modal deploy infra/modal_ollama.py
```

The first deploy pulls `qwen2.5:7b` (~4.7 GB) and `bge-m3` (~1.2 GB)
into a persistent Modal Volume — adds ~3 minutes to the first cold
start. After that, weights persist across cold starts.

**Get your two values:**
- The deploy prints a URL like
  `https://<workspace>--peppercarrot-ollama-serve.modal.run` → that's
  `OLLAMA_BASE_URL`.
- Generate **proxy auth tokens** in the Modal dashboard:
  https://modal.com/settings → your workspace → **Proxy Auth Tokens** →
  Create. Copy both the Key (`wk-…`) and Secret (`ws-…`) — those become
  `MODAL_PROXY_TOKEN_ID` and `MODAL_PROXY_TOKEN_SECRET`.

Paste all three into `.env.production`.

**Smoke-test:**

```bash
set -a && source .env.production && set +a
curl -sS -H "Modal-Key: $MODAL_PROXY_TOKEN_ID" \
        -H "Modal-Secret: $MODAL_PROXY_TOKEN_SECRET" \
        "$OLLAMA_BASE_URL/api/tags"
```

You want HTTP 200 with JSON listing both models.

---

## Step 2 — Provision Neon (Postgres)

1. Sign in at https://console.neon.tech, **Create a project**, region
   near your Fly region (default Fly is `iad`, so Neon `us-east-2`
   works well).
2. Open the project → **Connection Details** panel.
3. **Copy two connection strings** — Neon shows a toggle between
   **Pooled** and **Unpooled**:
   - **Pooled** (URL has `-pooler` in the hostname) → goes into
     `POSTGRES_RESTORE_URL`. Used by `psql` to load the seed at boot.
   - **Unpooled** (drop `-pooler` from the hostname) → goes into
     `DATABASE_URL_OVERRIDE`. Used by the backend's async driver at
     runtime.

4. Paste them into `.env.production`, **changing only the scheme** for
   `DATABASE_URL_OVERRIDE`:

   ```
   POSTGRES_RESTORE_URL=postgresql://neondb_owner:PASS@ep-XXXX-pooler.REGION.aws.neon.tech/neondb?sslmode=require
   DATABASE_URL_OVERRIDE=postgresql+asyncpg://neondb_owner:PASS@ep-XXXX.REGION.aws.neon.tech/neondb?sslmode=require
   ```

   The differences are intentional:
   - `postgresql+asyncpg://` tells SQLAlchemy "use the async driver."
     `postgresql://` is the libpq scheme that `psql` expects.
   - `?sslmode=require` works for both. `db/session.py` translates the
     URL param into the format asyncpg actually accepts — don't worry
     about `?ssl=true`.

> **Why two endpoints?** asyncpg uses *prepared statements* — it tells
> the database "remember this query plan." Neon's pooler in transaction
> mode hands each query to a different backend, which has never seen
> the prepared statement, and asyncpg errors out. The unpooled endpoint
> connects directly, sidesteps the issue. `psql` doesn't use prepared
> statements, so the pooler is fine for the one-shot seed restore.

---

## Step 3 — Provision Cloudflare R2 (image storage)

1. Cloudflare dashboard → **R2** (left sidebar) → **Create bucket**,
   name it `peppercarrot-images`. Region: Automatic.

2. Get an **API token**: R2 → **Manage API Tokens** → **Create API
   token** → permissions **"Object Read & Write"** scoped to your
   bucket. Cloudflare shows three values:
   - **Access Key ID** → `R2_ACCESS_KEY_ID`
   - **Secret Access Key** → `R2_SECRET_ACCESS_KEY` (shown **once** —
     copy it now)
   - **Endpoint URL** — only used by clients like rclone; not needed in
     `.env`.

3. Get your **Account ID**: R2 page → right sidebar shows it (32-char
   hex). → `R2_ACCOUNT_ID`.

4. **Enable public access** on the bucket: bucket page → **Settings**
   → scroll to **Public access**. Pick one:
   - **R2.dev subdomain (fastest):** click **Allow Access** under
     "R2.dev subdomain". Cloudflare gives you
     `https://pub-xxxxxxxxxxxx.r2.dev`. That whole URL (no trailing
     slash) is `R2_PUBLIC_URL_PREFIX`.
   - **Custom domain:** **Connect Domain** under "Custom Domains",
     enter a subdomain on Cloudflare DNS. Prefix becomes
     `https://images.your-domain.com`.

5. Paste all four values plus `R2_BUCKET=peppercarrot-images` into
   `.env.production`.

6. **Configure rclone.** The interactive prompts can be flaky, so the
   reliable path is to write the config directly:

   ```bash
   $EDITOR ~/.config/rclone/rclone.conf
   ```

   Paste, replacing the placeholders:

   ```ini
   [r2]
   type = s3
   provider = Cloudflare
   access_key_id = <R2 Access Key ID>
   secret_access_key = <R2 Secret Access Key>
   endpoint = https://<R2 Account ID>.r2.cloudflarestorage.com
   acl = private
   ```

   Verify:
   ```bash
   rclone lsd r2:
   ```
   Should print `peppercarrot-images`.

7. **Scrub local `.DS_Store` files first** if you're on macOS. Finder
   writes these into every directory you browse to, and a naive
   `rclone copy` will happily upload them — including the leak of
   `.DS_Store` files being publicly readable at the bucket prefix.

   ```bash
   find data/images data/world-graph/images -name .DS_Store -delete
   ```

8. **Upload the images.** Two `rclone` commands — the `--exclude` flags
   defend against any `.DS_Store` files that snuck through and the
   2 MB `-original.jpg` source files the frontend never reads.

   ```bash
   rclone copy data/images r2:peppercarrot-images --progress \
       --exclude ".DS_Store" --exclude "**/.DS_Store" \
       --exclude "**/*-original.jpg"
   rclone copy data/world-graph/images r2:peppercarrot-images/world-graph/images --progress \
       --exclude ".DS_Store" --exclude "**/.DS_Store"
   ```

   The first command takes a few minutes (depends on how many episodes
   you've ingested; ~36 MB for a 12-episode ingest with `-original.jpg`
   excluded, vs. ~177 MB if you keep them). The second is small (a few
   MB of avatars).

   > **`copy` is additive — it never deletes.** If you re-deploy after
   > re-ingesting (different episode slugs, a different episode set,
   > or just to drop the originals), use `rclone sync` instead and
   > target the `episodes/` subdirectory to leave `world-graph/`
   > alone. See the [Pruning stale uploads from R2](#pruning-stale-uploads-from-r2)
   > recipe in Operations for the dry-run-first form.

9. **Verify keys match what the database expects.** The DB stores keys
   like `episodes/ep01-potion-of-flight/pages/001-display.webp` and
   `world-graph/images/carrot-thumb.webp`:

   ```bash
   # One directory per episode you ingested (12 lines for ep01–12, etc.).
   rclone lsf r2:peppercarrot-images/episodes/ --dirs-only | sort
   # Quick public-read smoke test:
   curl -I "https://pub-XXXX.r2.dev/world-graph/images/carrot-thumb.webp"
   # Expect HTTP/2 200 with content-type: image/webp.
   ```

---

## Step 4 — Dump the Postgres seed

The Docker image bakes in `data/seed.sql` and the entrypoint restores
it on first boot. Generate the dump from your local Postgres:

```bash
./infra/dump_seed.sh
```

This writes `data/seed.sql` (a few hundred KB of schema + data,
gitignored). The script prints how many tables and data rows were
captured — if it says `0 data rows (schema only)`, your local Postgres
has the schema but no data, and you should go back to README
Steps 7–11 before deploying.

**Re-run this any time your local DB changes** — after ingesting a new
episode, editing the world-graph YAML, fixing a character description,
etc. Then `fly deploy` rebuilds the image with the new seed.

> **The canonical pattern is `./infra/dump_seed.sh && fly deploy`** as a
> single chained command (see Step 5). The Dockerfile's `COPY data/seed.sql`
> line will fail with a Docker-side `no source files were specified`
> error if you skip the dump — chaining them removes the ordering
> footgun entirely.

> **Why bake the seed in?** Most production setups would `psql -f
> seed.sql` from a CI step. We bake it in to keep the demo deploy a
> single self-contained command. The trade-off is rebuild time (~1 min
> for the Docker layer cache to invalidate) vs. operational simplicity.
> For a portfolio demo, simplicity wins.

---

## Step 5 — Deploy the backend (Fly.io)

```bash
fly auth login
fly launch --no-deploy --copy-config
```

`--copy-config` reuses the committed `fly.toml`, so the **app name comes
from that file** (`app = 'pepper-carrot-ai-flipbook-workshop'` in this
repo). Fly app names are global, so if that one is taken, edit `app =` in
`fly.toml` to something unique and use your name as the hostname
everywhere below. The launch wizard will decline to create a Postgres or
Redis (we have Neon already).

**Push every secret in `.env.production` to Fly in one shot:**

```bash
set -a && source .env.production && set +a && \
fly secrets set \
  POSTGRES_RESTORE_URL="$POSTGRES_RESTORE_URL" \
  DATABASE_URL_OVERRIDE="$DATABASE_URL_OVERRIDE" \
  OLLAMA_BASE_URL="$OLLAMA_BASE_URL" \
  MODAL_PROXY_TOKEN_ID="$MODAL_PROXY_TOKEN_ID" \
  MODAL_PROXY_TOKEN_SECRET="$MODAL_PROXY_TOKEN_SECRET" \
  R2_ACCOUNT_ID="$R2_ACCOUNT_ID" \
  R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
  R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  R2_BUCKET="$R2_BUCKET" \
  R2_PUBLIC_URL_PREFIX="$R2_PUBLIC_URL_PREFIX" \
  CORS_ORIGINS="$CORS_ORIGINS"
```

Then deploy. **Chain `dump_seed.sh` to `fly deploy`** so a fresh dump
is guaranteed to be on disk for the Docker build to pick up:

```bash
./infra/dump_seed.sh && fly deploy
```

What happens on the first deploy:

1. Docker builds the image (~2–3 min — installs deps, bakes
   `data/seed.sql`, `data/chroma/`, `data/world-graph/`).
2. Image pushed to Fly's registry (~2 min for the first push, faster
   on subsequent deploys thanks to layer cache).
3. A 512 MB shared-CPU machine boots. `entrypoint.sh` notices the
   empty Neon DB, runs `psql < /app/data/seed.sql`, then starts
   uvicorn.

**Verify:**

```bash
curl https://pepper-carrot-ai-flipbook-workshop.fly.dev/health
# {"status":"ok"}

curl https://pepper-carrot-ai-flipbook-workshop.fly.dev/api/episodes | head -c 300
# JSON array of episode metadata
```

If `/health` works but `/api/episodes` returns 500, check `fly logs` —
most likely a database URL issue (see Troubleshooting).

---

## Step 6 — Deploy the frontend (Cloudflare Pages)

1. Cloudflare dashboard → **Workers & Pages** → **Create application**
   → **Pages** tab → **Connect to Git** → pick your repo.
2. **Build settings:**
   - Framework preset: **None**
   - Build command: `cd frontend && npm install && npm run build`
   - Build output directory: `frontend/dist`
   - Root directory: leave blank
3. **Environment variables** (Build settings → Environment variables → add):
   - `VITE_API_BASE_URL` = `https://pepper-carrot-ai-flipbook-workshop.fly.dev`

   Vite inlines this at build time, so the deployed JS calls your Fly
   backend directly. **Without this var, the frontend will try to call
   `localhost:8000`** and break in the browser.

4. **Save and Deploy.** Cloudflare prints a URL like
   `https://pepper-carrot-ai-flipbook-workshop.pages.dev`.

5. **Update `CORS_ORIGINS` on Fly** to match this URL exactly (no
   trailing slash, scheme included), then redeploy:

   ```bash
   fly secrets set CORS_ORIGINS='["https://pepper-carrot-ai-flipbook-workshop.pages.dev"]'
   ```

   Fly redeploys automatically when secrets change.

---

## Step 7 — End-to-end test

Open the Pages URL in a browser. Expected flow:

1. Episode picker loads with cover thumbnails (those are R2 URLs —
   broken images mean the R2 keys or `R2_PUBLIC_URL_PREFIX` are wrong).
2. Click an ingested episode — the flipbook shows page 1.
3. Type a chat question. The first answer can take 15–30s if Modal had
   to cold-start; subsequent answers are fast.
4. Click the **🌐 World** button — the world-graph overlay slides in,
   gated by exactly the same spoiler boundary the chat sits behind.

If chat + the world graph both work end-to-end, the demo is live.

---

## Operations

### Re-deploying after ingestion changes

You added a new episode locally. To reflect it in prod:

```bash
# 1. Re-dump the seed (picks up the new episode rows + new chunks).
./infra/dump_seed.sh

# 2. Upload the new episode's images to R2 (additive — copy never deletes,
#    so existing R2 objects stay put).
rclone copy data/images r2:peppercarrot-images --progress \
    --exclude ".DS_Store" --exclude "**/.DS_Store" \
    --exclude "**/*-original.jpg"

# 3. Redeploy backend (rebuilds image with the updated seed.sql + Chroma).
fly deploy
```

The entrypoint sees an already-seeded Neon and skips the SQL restore.
The Chroma directory inside the image, however, is replaced — so new
episodes' embeddings come along for the ride. **You can't add new
episodes without redeploying the backend** (Chroma is baked, not
external).

### Pruning stale uploads from R2 {#pruning-stale-uploads-from-r2}

`rclone copy` (the default in this guide) is **additive — it never
deletes**. That's the right behavior for incremental re-deploys, but it
also means that if you previously uploaded episodes you no longer have
locally (a different episode set, a different ingest run), they stay
in the bucket forever. To make R2 mirror your local `data/images/`
exactly, swap `copy` for `sync`:

```bash
# 1. DRY RUN first — sync deletes, and a wrong-shaped source path will
#    happily wipe data you wanted to keep. The episodes/ target leaves
#    the world-graph/ prefix in the bucket untouched.
rclone sync data/images/episodes r2:peppercarrot-images/episodes \
    --exclude ".DS_Store" --exclude "**/.DS_Store" \
    --exclude "**/*-original.jpg" \
    --progress --dry-run

# 2. Read the "would delete" lines carefully. If the list matches what
#    you expect (e.g. ep13–ep39 you no longer have locally), drop --dry-run:
rclone sync data/images/episodes r2:peppercarrot-images/episodes \
    --exclude ".DS_Store" --exclude "**/.DS_Store" \
    --exclude "**/*-original.jpg" \
    --progress

# 3. Clean any straggler junk at the bucket root that the sync didn't
#    cover (it only touched episodes/).
rclone delete r2:peppercarrot-images/.DS_Store 2>/dev/null || true
```

Verify:

```bash
# One directory per episode locally — should match what's in data/images/episodes/.
rclone lsf r2:peppercarrot-images/episodes/ --dirs-only | sort
# Two prefixes total in the bucket — episodes/ and world-graph/. Nothing else.
rclone lsf r2:peppercarrot-images --dirs-only
# Total size — ~36 MB if you excluded -original.jpg; ~177 MB if you kept them.
rclone size r2:peppercarrot-images
```

The frontend only ever reads `-display.webp` and `-thumbnail.webp`
variants at runtime, so excluding `-original.jpg` shrinks the bucket
~4× without affecting anything the user sees. Cosmetic, not functional.

### Where to find logs

| Service | Command / URL |
|---|---|
| Backend (Fly) | `fly logs` |
| Modal | `modal app logs peppercarrot-ollama` |
| Cloudflare Pages build | dashboard → Workers & Pages → project → Deployments → Build log |
| Browser console (frontend) | DevTools → Console + Network tabs |

### Cost monitoring

- **Modal:** dashboard → Usage. GPU seconds + volume storage. The
  biggest cost item; expect $5–10/mo at portfolio traffic.
- **Fly:** dashboard → Billing. Sleeping machines are free; only
  charges if you exceed the small free monthly allowance.
- **Neon, R2, Pages:** all have generous free tiers; likely never see
  a bill.

---

## Alternative: skip Modal entirely (Anthropic + Voyage AI)

The default flow puts qwen2.5:7b and bge-m3 on a Modal GPU because the
series is *about* local-first self-hosted inference. If that constraint
doesn't matter to you and you'd rather:

- pay ~$0.10/mo for the chat layer instead of ~$5–10/mo,
- have zero cold-start latency on the first answer,
- and not operate a Modal endpoint at all,

…the [Post 3 provider abstraction](../docs/decisions/0002-model-provider-abstraction.md)
supports it via config alone — no code changes needed. The backend's
`AnthropicChatClient` and the new `VoyageEmbeddingClient` ship in
`backend/app/clients/`. The trade-off (and the cost comparison table) is
documented in §7 of Post 10.

**Three deltas from the default flow above:**

1. **Skip Step 1** (`modal deploy infra/modal_ollama.py`). There is no
   Modal endpoint to deploy.

2. **Re-index Chroma locally with Voyage embeddings** before
   `dump_seed.sh`. Voyage's vectors live in a different space than
   bge-m3's, so existing `pages_v1` / `wiki_v1` collections need
   rebuilding:

   ```bash
   # In your local .env, switch the embedding provider:
   echo 'EMBEDDING_PROVIDER=voyage'  >> .env
   echo 'VOYAGE_API_KEY=pa-...'       >> .env
   echo 'VOYAGE_MODEL=voyage-3-lite'  >> .env

   # Wipe the bge-m3 collections and re-ingest:
   rm -rf data/chroma
   cd ingestion && uv run python ingest.py ep01-potion-of-flight  # repeat per episode
   uv run python ingest_wiki.py
   ```

   Postgres + R2 stay put; only Chroma rebuilds.

3. **Push the alternative secrets to Fly** (in Step 5, instead of the
   Modal + Ollama secrets):

   ```bash
   set -a && source .env.production && set +a && \
   fly secrets set \
     CHAT_PROVIDER="anthropic" \
     ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
     ANTHROPIC_MODEL="$ANTHROPIC_MODEL" \
     EMBEDDING_PROVIDER="voyage" \
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

   ./infra/dump_seed.sh && fly deploy
   ```

The `.env.production.example` template carries a commented-out block for
the alternative path; uncomment it and fill in the values instead of the
Modal block.

The R2 step (Step 3) and the Neon step (Step 2) are unchanged — they're
not provider-coupled to the chat layer. The frontend (Step 6) and the
end-to-end test (Step 7) are also unchanged.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `fly deploy` errors at build with `COPY failed: no source files were specified for source: data/seed.sql` | Step 4 (`./infra/dump_seed.sh`) was skipped or run from the wrong directory | Run `./infra/dump_seed.sh && fly deploy` from the repo root. If the dump prints `0 data rows (schema only)`, your local Postgres is empty — go back to README Steps 7–11 first. |
| `/api/episodes` returns `[]` from the deployed backend | `dump_seed.sh` ran against an empty local Postgres | Re-ingest at least Episode 1 locally, re-run `./infra/dump_seed.sh && fly deploy`. |
| `/health` 200 but `/api/episodes` 500 | DB URL wrong | Re-check `DATABASE_URL_OVERRIDE` (unpooled, `postgresql+asyncpg://…?sslmode=require`). `fly logs` shows the asyncpg error. |
| `psql: invalid connection option` in `fly logs` | `POSTGRES_RESTORE_URL` has wrong scheme | Re-set with `postgresql://…` |
| `prepared statement "__asyncpg_stmt…" does not exist` | Used the **pooled** endpoint for `DATABASE_URL_OVERRIDE` | Switch to unpooled (drop `-pooler` from the hostname) |
| Browser shows "CORS error" | `CORS_ORIGINS` doesn't match the Pages URL exactly | `fly secrets set CORS_ORIGINS='["https://exact-pages-url"]'` |
| Episode covers / pages broken in browser | R2 keys are wrong, or `R2_PUBLIC_URL_PREFIX` mismatched | `rclone ls r2:peppercarrot-images \| head` and compare to `pages.image_url` in DB |
| R2 bucket still contains episodes you no longer have locally | `rclone copy` is additive and never deletes | Use `rclone sync` instead — see [Pruning stale uploads from R2](#pruning-stale-uploads-from-r2). Always run with `--dry-run` first. |
| `.DS_Store` files publicly readable on the bucket prefix | macOS Finder writes them; an earlier `rclone copy` without `--exclude` swept them in | `rclone delete r2:peppercarrot-images --include "**/.DS_Store" --include ".DS_Store"`. Add the `--exclude ".DS_Store"` flag to every future `rclone copy` / `sync`. |
| Chat 401s | Modal proxy auth tokens don't match | Regenerate in Modal dashboard, `fly secrets set MODAL_PROXY_TOKEN_ID=… MODAL_PROXY_TOKEN_SECRET=…` |
| First chat message hangs ~30s | Modal cold start | Expected. Subsequent messages within `scaledown_window` (5 min) are instant. |
| `fly logs` shows app-startup tracebacks | Config issue — wrong env value, missing secret | The traceback's last few lines name the failing field; cross-check `.env.production`. |

If you hit something not in this table, `fly logs --no-tail | tail -50`
usually has the answer in the last 30 lines.
