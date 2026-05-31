"""Retrieval service — where the spoiler boundary lives.

Wraps the ChromaDB read side. Two modes, chosen by the user via the chat UI's
mode (a per-message choice, not something the model decides):

- **page** — questions about the comic narrative. Queries `pages_v1`,
  spoiler-filtered: the chat never receives text from pages the reader hasn't
  reached. The boundary is a query-time `where` clause built from the reader's
  saved position, not a prompt instruction. (Introduced in Post 6.)
- **wiki** — questions about the *Pepper&Carrot* universe (characters, witch
  schools, places, lore). Queries `wiki_v1` with **no** spoiler filter: facts
  about the world aren't plot spoilers, and the user explicitly asked for them
  by choosing wiki mode. (Introduced in Post 7.)

Splitting the modes at the UI — rather than asking the chat model to pick —
gives each path a small, focused prompt and keeps the answer source explicit
to the reader. See CLAUDE.md conventions 2 and 4.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import chromadb
from chromadb.errors import NotFoundError as ChromaNotFoundError

from app.clients.embedding import EmbeddingClient

logger = logging.getLogger(__name__)

Mode = Literal["page", "wiki"]
"""The chat mode, chosen by the user per message via the UI chips."""

PAGES_COLLECTION = "pages_v1"
"""Page descriptions, written by ingestion (Post 4). Each vector carries
metadata `{episode_number, page_number, source_table, source_id}`. The spoiler
filter reads the first two; `source_id` is the page's Postgres primary key."""

WIKI_COLLECTION = "wiki_v1"
"""Universe lore, written by the wiki ingestion (Post 7). Each vector carries
`{source_table: "wiki", source_id}` — deliberately **no** episode/page, because
wiki facts are spoiler-exempt."""

# How many chunks each mode pulls. Page questions want a little nearby
# narrative context. Wiki used to land 5 whole multi-entity articles in
# the prompt (Post 7), which crowded out the on-topic ones; Post 9
# switched the wiki to summary-first (one tight ~150-word document per
# entity, authored by the `summarize-wiki` skill) and trimmed k to 3 so
# the prompt sees ~500 words of focused context. That's small enough that
# Post 8's OUTPUT RULES actually hold against qwen2.5:7b.
_PAGE_K = 3
_WIKI_K = 3


class CollectionNotReadyError(RuntimeError):
    """Raised when `pages_v1` doesn't exist yet — no episode has been ingested."""


@dataclass(frozen=True)
class RetrievedChunk:
    """A hit from Chroma, ready to be looked up in Postgres.

    Chroma stores only `(embedding, metadata, id)`. The canonical text lives in
    Postgres; `source_table` + `source_id` is how the orchestration layer fetches
    it back — see CLAUDE.md convention 4.
    """

    chroma_id: str
    source_table: str  # "pages" | "wiki"
    source_id: str
    score: float
    metadata: dict[str, Any]


class RetrievalService:
    """Owns the Chroma read client and the per-mode retrieval policy.

    Construct once per process and share it across requests via `app.state`.
    The spoiler filter is built inside `retrieve()` from the arguments the
    caller passes — it is not reachable from, or influenced by, the user's
    message.
    """

    def __init__(
        self,
        chroma_persist_dir: Path,
        embedding_client: EmbeddingClient,
    ) -> None:
        self._embedding_client = embedding_client
        self._client = chromadb.PersistentClient(path=str(chroma_persist_dir))

        # pages_v1 is required — without it, page-mode chat can't work.
        try:
            self._pages = self._client.get_collection(PAGES_COLLECTION)
        except ChromaNotFoundError as exc:
            raise CollectionNotReadyError(
                f"Chroma collection {PAGES_COLLECTION!r} not found at "
                f"{chroma_persist_dir}. Ingest at least one episode first — see "
                "the ingestion pipeline from Post 4."
            ) from exc

        # wiki_v1 is optional — wiki mode degrades to "no results" until the
        # wiki seed has been ingested (see ingestion/ingest_wiki.py, Post 7).
        try:
            self._wiki: Any | None = self._client.get_collection(WIKI_COLLECTION)
        except ChromaNotFoundError:
            logger.warning(
                "Chroma collection %r not found at %s — wiki-mode queries will "
                "return nothing until you run `uv run python ingest_wiki.py`.",
                WIKI_COLLECTION,
                chroma_persist_dir,
            )
            self._wiki = None

    async def retrieve(
        self,
        mode: Mode,
        query: str,
        *,
        current_episode_number: int,
        current_page_number: int,
    ) -> list[RetrievedChunk]:
        """Return chunks relevant to `query` for the given mode.

        - **page**: `pages_v1`, spoiler-filtered. Eligible content is any page
          of an earlier episode OR an earlier page of the current episode; the
          current page is excluded (`$lt`) because the orchestrator feeds its
          description into the prompt directly. The position integers come from
          the `chat_sessions` row, never from `query`.
        - **wiki**: `wiki_v1`, no filter. Universe facts aren't plot spoilers,
          and the user picked this mode on purpose.
        """
        embeddings = await self._embedding_client.embed_batch([query])
        query_embedding = embeddings[0]

        if mode == "page":
            where = self._spoiler_filter(current_episode_number, current_page_number)
            return await self._query(self._pages, query_embedding, where=where, k=_PAGE_K)
        if mode == "wiki":
            return await self._query(self._wiki, query_embedding, where=None, k=_WIKI_K)
        raise ValueError(f"Unknown retrieval mode: {mode}")

    @staticmethod
    def _spoiler_filter(current_episode: int, current_page: int) -> dict[str, Any]:
        """Build the Chroma `where` clause that enforces the spoiler boundary.

        The boundary is *lexicographic* on `(episode, page)`:

            an earlier episode (any page)   OR   this episode, an earlier page

        It is tempting to write the simpler `episode_number <= E AND
        page_number <= P`, but that is wrong. If the reader is on page 3 of
        episode 2, the simple form would drop page 20 of episode 1 — content
        fully behind them — because `20 <= 3` is false. The `$or` below keeps
        every page of every earlier episode and only gates pages *within* the
        current episode. `$lt` (not `$lte`) excludes the current page.
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
        collection: Any | None,
        query_embedding: list[float],
        *,
        where: dict[str, Any] | None,
        k: int,
    ) -> list[RetrievedChunk]:
        """Run one Chroma query and convert the result to `RetrievedChunk`s.

        `collection` is `None` for an optional collection that hasn't been
        ingested (wiki, before the seed runs) — in which case there's nothing
        to return.
        """
        if collection is None:
            return []

        # Chroma's query() is synchronous; offload it so we don't block the loop.
        kwargs: dict[str, Any] = {"query_embeddings": [query_embedding], "n_results": k}
        if where is not None:
            kwargs["where"] = where
        result = await asyncio.to_thread(collection.query, **kwargs)

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
