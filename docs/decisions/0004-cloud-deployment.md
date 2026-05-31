# ADR 0004: Cloud deployment — five services, one demo, ~$10/mo

**Status**: Accepted
**Date**: 2026-05-31

## Context

By the end of Post 9 the application runs end-to-end on a developer laptop —
FastAPI behind Postgres, Vite-served frontend, Ollama serving qwen2.5:7b and
bge-m3 on the same machine, ChromaDB embedded in the backend process. The
portfolio framing requires a public URL: a recruiter clicks a link, the
flipbook loads, the chat works.

The simplest possible production architecture is "one box": rent a VPS,
docker-compose, point a domain. It would work, but it doesn't match the
abstractions Post 3 set up. Each piece of the stack has a different shape —
some need a GPU, some need persistent storage, some need scale-to-zero —
and one box pays the worst-case cost of all of them combined (an always-on
GPU is ~$430/mo on the cheapest provider). The shape of the demo points
at fanning out instead.

## Decision

Run each piece on the provider that's good at its specific job, and pay
for each one at the rate it actually consumes:

| Piece | Provider | Why |
|---|---|---|
| Frontend (React) | Cloudflare Pages | Static CDN, free for portfolio traffic. |
| Backend (FastAPI) | Fly.io | Containers that scale to zero; free monthly allowance for a sleepy demo. |
| Database (Postgres) | Neon | Hosted Postgres with sleep-on-idle; free tier covers ~0.5 GB. |
| Image storage | Cloudflare R2 | S3-compatible bucket; free tier, no egress fees. |
| AI models (Ollama) | Modal | Serverless GPU — allocated on demand, idle = $0. |

The architecture honors the provider abstractions from Post 3 unchanged:
the chat client speaks Ollama HTTP whether Ollama is on `localhost:11434`
or on a Modal URL; the embedding client is the same; the storage backend
toggles between `LocalStorage` and `R2Storage` on one env var. The only
production-specific code is **(a)** the boto3-backed `R2Storage`
implementation finally landing in Post 10, and **(b)** the asyncpg
sslmode-→-ssl shim in `db/session.py` that Neon's URL format requires.

The runtime cost at portfolio traffic is dominated by Modal GPU seconds
(typically $5–10/month); everything else stays on free tiers. The total
target is ≤ $15/month, which is what Post 10 means by "~$10/mo."

## Consequences

**Positive**

- Each provider is paid only for what it serves. Idle ≈ $0 on every tier
  except the Modal model-weights volume (~$1/mo).
- Five separate services means five separate failure boundaries — a Modal
  cold start doesn't break the picker; an R2 outage doesn't break the chat;
  a Neon maintenance window doesn't take the frontend down.
- The provider seams from Post 3 are exercised end-to-end. The portfolio
  story isn't "I added Docker"; it's "the abstractions I argued for in
  Post 3 are the seams I needed in Post 10."
- The frontend is byte-identical between dev and prod (only the
  `VITE_API_BASE_URL` differs); same for the backend image (one Docker
  image, multiple environments per Fly secret).

**Negative**

- Five providers to monitor; five free-tier limits to know about.
- Cold starts are real. Modal first-request latency after idle is 15–30s
  (GPU + VRAM load). The workshop hides most of it behind a fire-and-forget
  warmup triggered when the reader opens a session, but if the user
  ingests *and* asks within a few seconds the first answer can still be
  slow. Trade-off baked in deliberately; the alternative is to keep one
  container always warm (~$430/mo), which doesn't match the portfolio
  budget.
- The backend image bakes `data/seed.sql`, `data/chroma`, and the
  world-graph YAML, so any data-layer change requires a re-deploy. For a
  demo that ingests once per few weeks this is acceptable; for a real
  product you'd factor data out of the image.
- Adding episodes after deploy requires re-running `infra/dump_seed.sh`
  and `rclone copy`, then redeploying. There's no in-place ingestion
  pipeline on prod.

## Alternatives considered

**One VPS (DigitalOcean droplet, Hetzner box, etc.) with docker-compose.**
Simpler to reason about; one host, one log file, one bill. But the only
shape on a VPS that runs qwen2.5:7b reasonably is "a box with a GPU,"
which starts around $0.20/hr (~$150/mo always-on) and doesn't fit the
budget. CPU-only inference at 7B is too slow to feel responsive — first
token would land in tens of seconds, and the streaming UX from Post 7
would feel broken.

**Serverless everything (Vercel + Supabase + Replicate).** All three
providers do the right things; the integration cost is similar to the
chosen stack. The reason against is portfolio framing: the same provider
abstraction that the series argued for would only get exercised at the
backend boundary (Replicate would replace Ollama at the same seam), but
the *story* of swapping the backend host between Fly and a single VPS is
more useful for a reader who hasn't deployed before. Fly's `fly deploy`
is also easier to inspect than Vercel's hosted build steps — you can
read `fly logs` and find the asyncpg traceback in 10 seconds, whereas
Vercel's build sandbox is more opinionated.

**A managed Postgres on Fly instead of Neon.** Fly's hosted Postgres
(`fly mpg`) is fine but the free machine is small, and Neon's
scale-to-zero on the database is a closer analog to what Fly does on the
compute side. Cost is comparable; the asymmetry is just that Neon's
sleep-on-idle is more aggressive, which matches the project's traffic
shape.

## What this doesn't cover

- Multi-region. The demo lives in one Fly region (`iad`) and one Neon
  region (`us-east-2`). Adding read replicas in EU is straightforward
  with Neon's branching but outside the post's scope.
- Authentication. The deployed demo is publicly readable; there's no
  email gate. Adding one in front of the chat endpoints would be a
  separate ADR.
- A real CI/CD pipeline. The workshop's deploy is `fly deploy` from a
  developer's laptop. A GitHub-Actions-based pipeline that runs
  `dump_seed.sh` and pushes is the obvious next step; the workshop ships
  without it to keep the post's scope on the architecture, not the
  automation.
