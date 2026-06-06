# ADR 0006: A stateless retrieval-inspection endpoint for the MCP eval surface

**Status**: Accepted (design) — not yet implemented
**Date**: 2026-06-06

## Context

A separate portfolio piece exposes this app over MCP (Model Context Protocol) as two repos:

- `pepper-carrot-mcp` — an MCP **server** wrapping this app as a thin adapter, with two tools:
  `search` (retrieval) and `ask` (full pipeline).
- `pepper-carrot-eval` — an MCP **client** that consumes those tools to score retrieval quality
  and end-to-end answer quality, with failure attribution.

Recon of the current API surface found that **no endpoint exposes retrieval results**. Retrieval
runs *inside* `ChatOrchestrator.stream_response` via `RetrievalService.retrieve`; the only signal
that escapes to a client is `retrieved_doc_ids` (bare Chroma IDs) in the terminal `done` SSE
event — **no scores, no chunk text, no metadata**. `RetrievedChunk` already carries `score`
(`1 - cosine_distance`) and full `metadata`, but the orchestrator discards everything except IDs.

The `ask` tool needs **no** app change — it replays the existing `POST /api/sessions` → `PATCH`
→ `POST /api/sessions/{id}/messages` (SSE) flow from the MCP server. But `search` has no backing
endpoint. This is the **only** backend change the whole MCP/eval project requires.

## Decision

Add **one** stateless, read-only endpoint, `POST /api/retrieve`, that surfaces the existing
retrieval path with scores + metadata + canonical text. It introduces **no new retrieval logic**:
it calls the same `RetrievalService.retrieve` (same Voyage embedding, same lexicographic `$or`
spoiler filter) and the same Postgres text lookup the chat pipeline uses.

To keep the text lookup DRY, lift `ChatOrchestrator._fetch_chunk_text` to a module-level
`fetch_chunk_text(db, chunks)` in `backend/app/retrieval/service.py`, called by **both** the
orchestrator and the new route (a behavior-preserving extract — guarded by `mypy --strict`,
`ruff`, and the existing tests).

### Contract

```
POST /api/retrieve            (application/json)
Request:
  { "mode": "page"|"wiki",          # required
    "query": str (1..2000),          # required; mirrors the chat message cap
    "k": int (1..20) = 5,            # optional; production retrieval uses 3
    "current_episode": int|null,     # REQUIRED iff mode == "page"
    "current_page": int|null }       # REQUIRED iff mode == "page"
200:
  { "mode": "page",
    "boundary": {"current_episode":2,"current_page":3} | null,   # null for wiki
    "chunks": [
      { "chroma_id", "source_table": "pages"|"wiki", "source_id",
        "score",                      # 1 - cosine_distance, straight from RetrievedChunk
        "metadata": {"episode_number":1,"page_number":10, ...},
        "text" } ] }                  # canonical Postgres text
Errors: 400 (page mode w/o position; empty/long query) · 422 · 429 (rate limit) · 503 (not ready)
```

### Notes & rationale

- **Position as a request param, not a session.** Deliberate: it makes the retrieval instrument
  stateless and lets the evaluator sweep `(episode, page)` to test the spoiler boundary
  deterministically. Retrieval *logic* is byte-identical to production; only the *source* of the
  boundary integers differs (caller-supplied vs. the trusted `chat_sessions` row). For an
  inspection instrument over public CC BY data, that is acceptable and useful.
- **No schema change, no migration.** Read-only; plain container redeploy (no `alembic upgrade`).
- **Rate-limited.** Reuse `SlidingWindowRateLimiter` from `api/ratelimit.py` (its own limiter — a
  Voyage embedding per call; cheaper than chat so a higher cap).
- **Wiring.** Stash `app.state.retrieval_service` in `lifespan` (alongside the orchestrator it
  already builds) so the route doesn't reach into orchestrator privates.
- **Authless** at the app edge stays as-is; the MCP server is also authless by design.

## Consequences

- One `fly deploy` of the backend ships this endpoint + the `fetch_chunk_text` lift together.
  The `ask` path and all other routes are unchanged.
- The deployed app gains a public retrieval-inspection surface. The spoiler boundary remains
  structural and unwidenable by the `query` string — proven by a new HTTP-layer test.

## Implementation plan

1. `retrieval/service.py`: extract `fetch_chunk_text(db, chunks)`; update `ChatOrchestrator` to call it.
2. `main.py` lifespan: also stash `app.state.retrieval_service`.
3. New `backend/app/api/retrieve.py`: Pydantic request/response models; validation
   (`mode=page ⇒ position`); rate limiter; call `retrieve` + `fetch_chunk_text`; map to response.
4. Register the router in `main.py` (`prefix="/api/retrieve"`).
5. `backend/tests/test_retrieve_api.py`: mirror `test_retrieval.py`'s spoiler assertions at the
   HTTP layer, **including the jailbreak-query test** (now reachable end-to-end), plus
   score/metadata/text passthrough and the `page`-without-position 400.
6. Deploy; `curl` smoke for both modes.

## Definition of Done

- [ ] `uv run mypy app/` clean; `uv run ruff check app/` clean.
- [ ] `uv run pytest` green, including the new `test_retrieve_api.py`.
- [ ] `POST /api/retrieve` returns ranked chunks with `score` + `metadata` + `text` for both modes.
- [ ] `mode=page` without a position → 400; oversized/empty `query` → 422/400; `k` clamped.
- [ ] Spoiler boundary holds end-to-end: no chunk with `(episode,page) ≥ cursor`; the jailbreak
      query cannot widen scope (HTTP-layer test passes).
- [ ] No SDK imports outside `clients/` (convention 1); `fetch_chunk_text` is the single shared
      text-lookup used by both the orchestrator and the route (no duplicated logic).
- [ ] No DB migration introduced; existing chat/episode/session/world-graph routes unchanged.
- [ ] Deployed to `pepper-carrot-ai-flipbook-workshop.fly.dev`; `curl` verifies both modes live.
- [ ] `README.md` / `CLAUDE.md` note the new route where the API surface is described.
