# ADR 0001: Local-first architecture

**Status**: Accepted
**Date**: 2026-04-25

## Context

We're building a portfolio/demo project. The natural temptation is to start cloud-first because that's the eventual deployment target.

## Decision

Build local-first. All core functionality must work on a developer laptop with no internet connection (after initial model downloads). Cloud deployment is a future state, not a starting state.

## Consequences

**Positive**
- No API rate limits during prompt iteration. We expect to re-ingest the entire corpus dozens of times while tuning the page-description prompt; doing this against a metered API would be expensive and slow.
- No cost anxiety. Free experimentation matters when the goal is finding the right prompts and chunking strategy.
- Forces clean abstractions. Every model and storage call must be swappable.
- Faster dev loop. Ollama on localhost is faster end-to-end for development than calling a remote API even if the remote model is faster per-token, because of network round-trip and rate-limiting friction.
- Easier to demo offline.

**Negative**
- Local chat model quality is below frontier API quality (the chat layer uses `qwen2.5:14b` text-only locally on 24GB+ machines, `qwen2.5:7b` on smaller ones). Mitigation: tight prompt engineering — see `_RESPONSE_FORMAT` in `core/prompts.py`, and the schema-enforced suggestion-chip generation in `chat.py` — plus the option to swap to `AnthropicChatClient` for production.
- Local inference is slower per-token. Mitigation: streaming hides most of this; chat responses still feel responsive.
- Hardware requirement. Need a machine that can run a 7B-class text model and the bge-m3 embedding model. Mitigation: Apple Silicon and recent NVIDIA GPUs are common enough that this is acceptable.

> **Update (2026-05-02):** the original "page descriptions will be richer with Claude than with Qwen2.5-VL" tradeoff was resolved differently than expected — page descriptions now come from Claude *via the `ingest-from-images` Claude Code skill*, which uses your Claude Code session (no API key, no per-call cost) to read images and write structured `PageDescription` JSON. Result: frontier-quality descriptions with no API spend, no local VLM dependency, no GGML crashes. See ADR 0004.

## Alternatives considered

- **Cloud-first with API keys from day one.** Rejected: cost during prompt iteration is meaningful, and we lose the architectural discipline that makes the system portable.
- **Hybrid (local for ingestion, cloud for chat).** This is a reasonable production target, but starting fully local is simpler and ensures both paths are exercised.

## Migration path

The provider abstraction (see ADR 0002) means cloud migration is a config change. The expected target deployment uses local for ingestion (cheap, infrequent) and cloud for chat (better quality, on the user-facing critical path).
