"""Retrieval layer — spoiler-safe vector search over page descriptions.

The single public surface is `RetrievalService`. It owns the ChromaDB read
client and the spoiler filter; everything else in the app talks to it through
`retrieve()`. See `service.py` and CLAUDE.md convention 2.
"""

from app.retrieval.service import (
    PAGES_COLLECTION,
    CollectionNotReadyError,
    RetrievalService,
    RetrievedChunk,
)

__all__ = [
    "PAGES_COLLECTION",
    "CollectionNotReadyError",
    "RetrievalService",
    "RetrievedChunk",
]
