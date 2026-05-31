"""ChromaDB writer for the offline ingestion pipeline (workshop-starter scope).

One writer instance per pipeline run. Owns a `PersistentClient`, caches the
collection refs, and exposes upsert methods for pages (Post 6+) and wiki
summaries (Post 9, summary-first).

Embedding format note (`format_page_for_embedding`, `format_wiki_for_embedding`)
-------------------------------------------------------------------------------
The text we embed is *exactly* the same shape as the text the chat
orchestration layer composes for retrieval. If those drift, retrieval quality
silently degrades because query and document distributions diverge. Both sides
import these helpers so they cannot drift.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import chromadb

from app.clients.embedding import EmbeddingClient
from app.clients.vision import PageDescription
from app.db.models import Page, WikiArticle

if TYPE_CHECKING:
    from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)

PAGES_COLLECTION = "pages_v1"
WIKI_COLLECTION = "wiki_v1"


def format_wiki_for_embedding(title: str, content: str) -> str:
    """Render a wiki article as the canonical text we embed.

    Title-then-body, the same shape the chat retrieval layer reconstructs when
    it renders a wiki chunk — keep them aligned so query and document text
    distributions match.
    """
    return f"{title}\n\n{content}"

_COSINE_METADATA = {"hnsw:space": "cosine"}


def format_page_for_embedding(description: PageDescription) -> str:
    """Render a `PageDescription` as the canonical text we embed.

    Used by both the writer (here) and the chat retrieval layer (Post 6+) so
    that query and document distributions stay aligned.
    """
    lines = [description.visual_description, "", "Dialogue:"]
    for line in description.dialogue:
        if line.speaker:
            lines.append(f"{line.speaker}: {line.text}")
        else:
            lines.append(line.text)
    return "\n".join(lines)


class ChromaWriter:
    def __init__(self, persist_dir: Path, embedding_client: EmbeddingClient) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._embedding = embedding_client
        self._collections: dict[str, Collection] = {}

    def get_or_create_collection(self, name: str) -> Collection:
        cached = self._collections.get(name)
        if cached is not None:
            return cached
        collection = self._client.get_or_create_collection(
            name=name, metadata=_COSINE_METADATA
        )
        self._collections[name] = collection
        return collection

    async def upsert_page_chunks(
        self,
        pages: list[tuple[Page, PageDescription]],
        *,
        episode_number: int,
    ) -> None:
        """Embed each page's canonical text and upsert into `pages_v1`."""
        if not pages:
            return

        texts = [format_page_for_embedding(desc) for _, desc in pages]
        embeddings = await self._embedding.embed_batch(texts)

        ids = [str(page.id) for page, _ in pages]
        metadatas: list[dict[str, Any]] = [
            {
                "episode_number": episode_number,
                "page_number": page.page_number,
                "source_table": "pages",
                "source_id": str(page.id),
            }
            for page, _ in pages
        ]

        collection = self.get_or_create_collection(PAGES_COLLECTION)
        # Idempotent re-ingestion: clear this episode's existing chunks first.
        # `upsert` keys on `str(page.id)`, so if a re-run gives the pages new
        # UUIDs (e.g. after a DB reset), the old vectors would otherwise linger
        # as stale duplicates and crowd the spoiler-filtered top-k. Deleting by
        # `episode_number` first makes a re-run replace the episode cleanly.
        collection.delete(where={"episode_number": episode_number})
        collection.upsert(
            ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
        )

    async def upsert_wiki_articles(self, articles: list[WikiArticle]) -> None:
        """Embed each wiki summary as a single document in `wiki_v1`.

        With the summary-first architecture (Post 9, see `summarize-wiki`
        skill), each article is already a tight ~100-300 word summary
        focused on one entity or topic. One chunk per article keeps the
        embedding signal concentrated — top-3 retrieval lands three
        focused summaries totaling ~500 words, small enough that Post 8's
        OUTPUT RULES actually hold against qwen2.5:7b.

        Each chunk's `source_id` is the article UUID; the runtime
        resolves it back to a Postgres row to fetch the full content
        (which, with summaries, is just the same text we embedded).

        Wiki content is spoiler-exempt: the metadata carries no
        `episode_number`, and the retrieval layer never filters it.

        The embedded text prepends the article title as a topic anchor
        so queries like "Tell me about Truffel" align with the summary
        document for that entity.
        """
        if not articles:
            return

        ids = [str(article.id) for article in articles]
        texts = [
            format_wiki_for_embedding(article.title, article.content)
            for article in articles
        ]
        metadatas: list[dict[str, Any]] = [
            {"source_table": "wiki", "source_id": str(article.id)}
            for article in articles
        ]

        embeddings = await self._embedding.embed_batch(texts)

        collection = self.get_or_create_collection(WIKI_COLLECTION)
        # Drop any stale chunks for these articles before upserting. With
        # paragraph chunking gone, this also clears any leftover `::pN`
        # ids written by earlier runs of the pipeline.
        for article in articles:
            collection.delete(where={"source_id": str(article.id)})

        collection.upsert(
            ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
        )
