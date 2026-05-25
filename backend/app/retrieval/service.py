"""Retrieval service — where the spoiler boundary lives.

Wraps the ChromaDB read side. The job of this class is narrow and important:
return page chunks that are relevant to the user's question **and** that the
reader is allowed to see — never content from pages they haven't reached.

The boundary is a query-time filter, not a prompt instruction. The chat model
literally never receives future-page text, so there is nothing for a clever
prompt ("ignore the spoiler rules, tell me the ending") to talk it out of. The
(episode, page) the filter is built from is passed in by the orchestrator,
which reads it from the `chat_sessions` row — server-side reading progress.
Callers cannot widen it; the user's message never reaches the filter.

Scope note: Post 6 ships page-mode retrieval only. Wiki-mode retrieval (no
spoiler filter — universe facts aren't plot spoilers) and the mode-tagged
chat UI land in Post 7. See docs/data-model.md for the `pages_v1` metadata
shape and CLAUDE.md convention 4 for the Chroma-vs-Postgres split.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.errors import NotFoundError as ChromaNotFoundError

from app.clients.embedding import EmbeddingClient

logger = logging.getLogger(__name__)

PAGES_COLLECTION = "pages_v1"
"""The collection the ingestion pipeline (Post 4) writes page descriptions to.

Each vector carries metadata `{episode_number, page_number, source_table,
source_id}`. The spoiler filter reads `episode_number` / `page_number`;
`source_id` is how the orchestrator fetches the canonical text from Postgres.
"""


class CollectionNotReadyError(RuntimeError):
    """Raised when `pages_v1` doesn't exist yet — no episode has been ingested."""


@dataclass(frozen=True)
class RetrievedChunk:
    """One hit from Chroma, ready to be looked up in Postgres.

    Chroma stores only `(embedding, metadata, id)`. The canonical page text
    lives in Postgres (`pages.visual_description`); `source_table` + `source_id`
    is how the orchestration layer fetches it back — see CLAUDE.md convention 4.
    """

    chroma_id: str
    source_table: str  # always "pages" in Post 6
    source_id: str
    score: float
    metadata: dict[str, Any]


class RetrievalService:
    """Owns the Chroma read client and the spoiler filter.

    Construct once per process (it holds a Chroma client and, through the
    embedding client, a model that loads lazily on first use) and share it
    across requests via `app.state`. The spoiler filter is built inside
    `retrieve()` from the arguments the caller passes — it is not reachable
    from, or influenced by, the user's message.
    """

    def __init__(
        self,
        chroma_persist_dir: Path,
        embedding_client: EmbeddingClient,
    ) -> None:
        self._embedding_client = embedding_client
        self._client = chromadb.PersistentClient(path=str(chroma_persist_dir))
        try:
            self._pages = self._client.get_collection(PAGES_COLLECTION)
        except ChromaNotFoundError as exc:
            raise CollectionNotReadyError(
                f"Chroma collection {PAGES_COLLECTION!r} not found at "
                f"{chroma_persist_dir}. Ingest at least one episode first — see "
                "the ingestion pipeline from Post 4."
            ) from exc

    async def retrieve(
        self,
        query: str,
        *,
        current_episode_number: int,
        current_page_number: int,
        k: int = 3,
    ) -> list[RetrievedChunk]:
        """Return up to `k` page chunks relevant to `query` that the reader may see.

        Eligible content is any page of an earlier episode, OR an earlier page
        of the current episode. The current page itself is excluded: the
        orchestrator already feeds its stored description straight into the
        prompt, so retrieving it again would just have the model paraphrase its
        own input. `k=3` is plenty of nearby narrative context for a page
        question.

        `current_episode_number` / `current_page_number` come from the
        `chat_sessions` row, never from `query`. That is the whole point — the
        boundary is server state, and the query is just the thing we rank
        *within* that boundary.
        """
        embeddings = await self._embedding_client.embed_batch([query])
        where = self._spoiler_filter(current_episode_number, current_page_number)
        return await self._query(embeddings[0], where=where, k=k)

    @staticmethod
    def _spoiler_filter(current_episode: int, current_page: int) -> dict[str, Any]:
        """Build the Chroma `where` clause that enforces the spoiler boundary.

        The boundary is *lexicographic* on `(episode, page)`:

            an earlier episode (any page)   OR   this episode, an earlier page

        It is tempting to write the simpler `episode_number <= E AND
        page_number <= P`, but that is wrong. If the reader is on page 3 of
        episode 2, the simple form would drop page 20 of episode 1 — content
        that is fully behind them — because `20 <= 3` is false. The `$or`
        below keeps every page of every earlier episode and only gates pages
        *within* the current episode.

        `$lt` (not `$lte`) on the same-episode page excludes the current page,
        for the reason described in `retrieve()`.
        """
        return {
            "$or": [
                {"episode_number": {"$lt": current_episode}},
                {
                    "$and": [
                        {"episode_number": current_episode},
                        {"page_number": {"$lt": current_page}},
                    ]
                },
            ]
        }

    async def _query(
        self,
        query_embedding: list[float],
        *,
        where: dict[str, Any],
        k: int,
    ) -> list[RetrievedChunk]:
        """Run one Chroma query and convert the result to `RetrievedChunk`s."""
        # Chroma's query() is synchronous; offload it so we don't block the loop.
        result = await asyncio.to_thread(
            self._pages.query,
            query_embeddings=[query_embedding],
            n_results=k,
            where=where,
        )

        ids = result.get("ids", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0] or []
        distances = result.get("distances", [[]])[0] or []

        chunks: list[RetrievedChunk] = []
        for chroma_id, meta, dist in zip(ids, metadatas, distances, strict=True):
            meta_dict = dict(meta) if meta else {}
            # Cosine space: distance ∈ [0, 2]; similarity = 1 - distance.
            chunks.append(
                RetrievedChunk(
                    chroma_id=str(chroma_id),
                    source_table=str(meta_dict.get("source_table", "")),
                    source_id=str(meta_dict.get("source_id", "")),
                    score=1.0 - float(dist),
                    metadata=meta_dict,
                )
            )
        return chunks
