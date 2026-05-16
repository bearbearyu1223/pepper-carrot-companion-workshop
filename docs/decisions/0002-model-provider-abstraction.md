# ADR 0002: Model provider abstraction

**Status**: Accepted; partially superseded by ADR 0004 (vision)
**Date**: 2026-04-25 (last updated 2026-05-02)

> **Update (2026-05-02):** The vision-provider portion of this ADR has been superseded — `OllamaVisionClient` and `AnthropicVisionClient` were both implemented, evaluated, and removed in favour of a fundamentally different approach (Claude Code skill writes `PageDescription` JSONs; `JsonFileVisionClient` consumes them). See ADR 0004 for the rationale and trade-offs. The chat- and embedding-provider portions of this ADR remain in effect: both `OllamaChatClient` + `AnthropicChatClient` and `SentenceTransformersEmbeddingClient` + `OllamaEmbeddingClient` are live and switchable via `.env`.
>
> **Update (2026-05-02, second pass):** The `ChatClient` Protocol gained a second method, `complete(system, messages, *, max_tokens, json_format)`, for short non-streaming side-channel calls (currently used for suggestion-chip generation; future use for classifiers). `json_format` accepts `False` (no constraint), `True` (Ollama's bare `format: "json"` — emits valid JSON without a schema), or a JSON-Schema dict (Ollama enforces it during sampling). `AnthropicChatClient.complete()` ignores `json_format` and trusts the prompt. The Protocol still cleanly accommodates both providers — exactly the design intent of the original ADR.

## Context

Three distinct model roles in the system:
- **Vision**: page description during ingestion, multimodal chat at runtime
- **Chat**: text generation in the chat orchestration pipeline
- **Embedding**: chunk embedding for retrieval

Each role has multiple viable providers (Ollama with various open models, Anthropic, OpenAI, Voyage). The choice depends on local-vs-cloud, hardware, cost, and quality requirements that vary by project phase.

## Decision

Define a `Protocol` interface for each role. Concrete implementations are factories selected by configuration. **No code outside `backend/app/clients/` may import a provider SDK directly.**

```python
class VisionClient(Protocol):
    async def describe_page(
        self,
        image: Image,
        previous_page_description: str | None,
        cast_list: list[str],
    ) -> PageDescription: ...

class ChatClient(Protocol):
    def stream(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]: ...

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int = 256,
        json_format: bool | dict[str, Any] = False,
    ) -> str: ...

class EmbeddingClient(Protocol):
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

Implementations originally planned: `OllamaVisionClient`, `AnthropicVisionClient`, `OllamaChatClient`, `AnthropicChatClient`, `SentenceTransformersEmbeddingClient`, `OllamaEmbeddingClient`, `VoyageEmbeddingClient`.

(Current state: the two vision clients were removed per ADR 0004; `JsonFileVisionClient` is the sole vision implementation. The chat and embedding clients above are live as planned.)

## Consequences

**Positive**
- Local↔cloud swap is a config change, not a refactor.
- Hybrid setups (local ingestion + cloud chat) are trivial.
- Adding a new provider doesn't touch any caller.
- Tests can use a stub implementation easily.

**Negative**
- Slight indirection cost. Calling code can't access provider-specific features (e.g., Anthropic's prompt caching) without extending the interface.
- Interface design has to accommodate the union of provider capabilities. Mitigation: design for the common subset; expose advanced features via optional kwargs that some implementations may ignore.

## Discipline notes

- The factory pattern lives in `clients/__init__.py` and reads `settings`. Callers receive an interface, never a concrete class.
- New embedding model? Don't just swap `EMBEDDING_MODEL` — the resulting embeddings are incompatible with existing vectors. Bump the collection version (`pages_v2_voyage`) and re-ingest.
- When tempted to add a provider-specific shortcut, instead extend the Protocol and add no-op or fallback behavior in implementations that don't support it.

## Alternatives considered

- **Direct SDK calls everywhere with adapter shims.** Rejected: leaks provider concepts (model names, parameter schemas) into business logic.
- **A single "ModelClient" that handles all three roles.** Rejected: vision/chat/embedding have genuinely different interfaces; one mega-Protocol obscures more than it clarifies.
- **LangChain or similar abstraction libraries.** Rejected: too heavy for this project's needs and forces patterns that don't fit (chains, agents). A 100-line custom abstraction is clearer.
