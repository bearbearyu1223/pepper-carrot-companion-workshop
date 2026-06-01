# ADR 0005: A managed-API deploy path — Anthropic + Voyage, no GPU

**Status**: Accepted
**Date**: 2026-06-01

## Context

[ADR 0004](0004-cloud-deployment.md) put the application on five providers
and chose Modal — serverless GPU serving Ollama (`qwen2.5:7b` + `bge-m3`) —
for the AI layer. That choice is load-bearing for the *series' thesis*:
the project exists to show local-first, self-hosted inference on commodity
hardware, and Post 8's prompt hardening is calibrated against
`qwen2.5:7b`'s specific limitations. Modal is the cloud expression of "run
your own model."

But the GPU is also the single most expensive and most operationally
involved piece of the deploy. It carries the only meaningful cold start
(15–30 s to allocate a GPU and load weights into VRAM), the only
per-second GPU bill (~$5–10/mo), the only model-weights volume to keep
warm (~$1/mo at rest), and the only endpoint with proxy-auth tokens to
manage. For a reader who doesn't care about the local-first framing — who
just wants the flipbook live, cheap, and instant — Modal is pure cost.

The provider abstractions from [Post 3](../decisions/0002-model-provider-abstraction.md)
were designed so that the AI layer could be swapped without touching the
orchestration, retrieval, or API code. This ADR records the decision to
*ship and document* the managed-API path as a first-class alternative, so
the abstraction's payoff is reproducible rather than hypothetical.

## Decision

Offer a second, fully documented deploy path that replaces Modal with two
hosted HTTP APIs:

| Piece | Default path (ADR 0004) | This path |
|---|---|---|
| Chat | Modal → Ollama `qwen2.5:7b` (T4 GPU) | Anthropic Messages API → `claude-haiku-4-5` |
| Embeddings | Modal → Ollama `bge-m3` | Voyage AI → `voyage-4-lite` |
| Everything else | Cloudflare Pages + Fly + Neon + R2 | **unchanged** |

The swap is **configuration only** — no code changes:

- `CHAT_PROVIDER=anthropic` selects the `AnthropicChatClient` that already
  ships in `backend/app/clients/chat.py` (it landed in Post 8 for the
  swap-in story and is reused here unchanged).
- `EMBEDDING_PROVIDER=voyage` selects the `VoyageEmbeddingClient` in
  `backend/app/clients/embedding.py` — a ~80-line HTTP client (thin POST
  to `api.voyageai.com/v1/embeddings`, defensive index-resort, mocked unit
  tests in `backend/tests/test_embedding.py`).
- The factory in `backend/app/clients/__init__.py` carries one branch per
  provider; both branches predate this ADR.

The artifacts this path adds are a dedicated env template
(`.env.production.anthropic.example`) and a standalone operational guide
(`docs/deployment-anthropic.md`). The default `docs/deployment.md` keeps a
short "Alternative" pointer to both.

The one operational asymmetry the reader must internalize: **the local
Chroma collections have to be rebuilt before deploy.** `pages_v1` and
`wiki_v1` were embedded with `bge-m3`. Voyage's `voyage-4-lite` produces
vectors in a different vector space, so the existing collections are
meaningless under the new embedder. Note that this is *not* a dimensionality
problem — `voyage-4-lite` and `bge-m3` are both 1024-dim by default — which
makes the failure mode quieter: the index is the right shape and still wrong,
so nothing crashes; retrieval just ranks on noise. Re-running the local
ingestion with `EMBEDDING_PROVIDER=voyage` rebuilds `data/chroma`; Postgres
and R2 are untouched because the canonical text and image bytes don't depend
on the embedder.

## Consequences

**Positive**

- **No GPU to operate.** No Modal deploy, no model-weights volume, no
  proxy-auth tokens, no `modal app logs` to read. Three of the deploy
  steps from ADR 0004 disappear.
- **Zero cold start on the first answer.** Both APIs are always-on from
  the caller's perspective. The Fly cold start (~5–10 s wake-from-zero)
  still exists, but the dominant 15–30 s Modal GPU cold start is gone.
- **~$0.10/mo for the chat layer** at portfolio traffic (~100 questions/mo)
  vs. ~$5–10/mo for Modal. The whole deploy moves to effectively-free.
- **Better chat quality out of the box.** `claude-haiku-4-5` clears the
  grounding and concision bar Post 8 had to fight `qwen2.5:7b` for. The
  prompt hardening still applies; it just has less work to do.
- **The Post 3 abstraction is exercised end-to-end, again.** Demonstrating
  that the AI layer swaps on two env vars and a re-index — with no diff
  outside `clients/` config — is itself the portfolio signal, regardless
  of which path the reader ships.

**Negative**

- **Prompts and embed-queries leave your infrastructure.** Every chat
  message goes to Anthropic; every retrieval query goes to Voyage. For a
  public CC-BY comic companion this is a non-issue, but it is the exact
  property the local-first thesis was protecting, and it should be named.
- **Abandons the series' thesis.** This path is "use someone else's
  model," which is the thing Posts 2–10 were deliberately *not* doing. It
  is the right pick when chat quality and zero cold start matter more than
  the local-first framing; it is the wrong pick if the framing is the
  point.
- **Two more vendor accounts + two more API keys** to manage and rotate.
- **A re-index step gated on getting the embedder right.** Deploying with
  a `bge-m3`-built Chroma against a Voyage runtime is a silent failure:
  retrieval returns IDs, the grounding text loads, but the *ranking* is
  garbage because the query vector and the stored vectors are in different
  spaces. The guide makes Step 2 (re-index) a hard prerequisite for this
  reason.

## Alternatives considered

**In-process `sentence-transformers` on Fly (no embeddings vendor).**
`EMBEDDING_PROVIDER=sentence-transformers` already works and keeps embed
queries on your own box. The catch is memory: `bge-m3` is ~1.5 GB resident,
so the 512 MB Fly machine isn't big enough — you'd bump the VM to 2 GB
(~$3/mo) and eat a longer Fly cold start (the model loads into RAM on every
container boot). It trades the Voyage dependency for a fatter, slower-booting
backend. Reasonable if data residency on embeddings matters; otherwise Voyage
is cheaper and lighter. Documented as a one-line note in the guide, not the
default.

**Keep Modal for embeddings only (`gpu=None`).** Run Modal CPU-only serving
just `bge-m3`, drop the chat model, point chat at Anthropic. Keeps the
existing Chroma collections (no re-index!) because the embedder doesn't
change. But it's an awkward middle: you still operate a Modal endpoint and
proxy auth for the thing you were trying to stop operating. Rejected as the
documented path because "skip Modal entirely" is the whole point; mentioned
as an escape hatch for readers who want to avoid the re-index.

**OpenAI / other hosted chat + embeddings.** Functionally equivalent — the
abstraction doesn't care. Not chosen because Anthropic + Voyage is the pairing
the series already wires up (`AnthropicChatClient` shipped in Post 8; Voyage is
Anthropic's recommended embeddings partner), so it requires zero new client
code. Adding an `OpenAIChatClient` would be a new `clients/` implementation and
a new factory branch — a different post.

## What this doesn't cover

- **Prompt caching economics at scale.** `AnthropicChatClient` already sets
  `cache_control: ephemeral`, so multi-turn prefixes are cached (~90% read
  discount). At portfolio traffic the absolute cost is noise either way; at
  product traffic the caching math would deserve its own analysis.
- **Voyage rate limits / batching.** The ingestion pipeline embeds in small
  batches well under Voyage's limits at workshop scale. A large back-catalog
  re-index would want backoff and larger batches.
- **Data-processing agreements.** Sending user prompts to third-party APIs has
  contractual implications for a real product (DPAs, retention settings). Out
  of scope for a public-domain demo; in scope the moment real user data flows.
