"""ChromaDB writer for the offline ingestion pipeline (workshop-starter scope).

One writer instance per pipeline run. Owns a `PersistentClient`, caches the
`pages_v1` collection ref, and exposes one upsert method.

Embedding format note (`format_page_for_embedding`)
---------------------------------------------------
The text we embed for a page is *exactly* the same shape as the text the chat
orchestration layer composes for retrieval (Post 6+). If those drift, retrieval
quality silently degrades because query and document distributions diverge.
Both sides import this helper so they cannot drift.

Wiki ingestion lives in the full project repo (later post); this starter only
ships the page path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import chromadb

from app.clients.embedding import EmbeddingClient
from app.clients.vision import PageDescription
from app.db.models import Page

if TYPE_CHECKING:
    from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)

PAGES_COLLECTION = "pages_v1"

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
        collection.upsert(
            ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
        )
