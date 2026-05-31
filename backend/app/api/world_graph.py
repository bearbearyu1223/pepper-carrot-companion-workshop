"""World-graph route — spoiler-filtered entities + relationships (Post 9).

The filter is structural — applied in SQL with row-value comparison so the
runtime never returns nodes or edges past the reader's current page. Same
shape as the page-mode RAG boundary from Post 6: the spoiler integers come
from the URL (validated against the episode's real page count), the model
never sees them, and an edge can only appear if its own debut AND both of
its endpoints' debuts are at or before the reader's cursor.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.episodes import get_storage_client
from app.clients import Storage
from app.db.models import Episode, Page, WorldEntity, WorldRelationship
from app.db.session import get_session

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[Storage, Depends(get_storage_client)]


class WorldNode(BaseModel):
    id: UUID
    slug: str
    name: str
    kind: str
    summary: str | None
    image_url: str | None  # composed at response time from the relative key
    x: float
    y: float
    episode_debut: int
    page_debut: int


class WorldEdge(BaseModel):
    id: UUID
    source: UUID
    target: UUID
    kind: str
    summary: str | None
    episode_debut: int
    page_debut: int


class WorldGraphResponse(BaseModel):
    nodes: list[WorldNode]
    edges: list[WorldEdge]


@router.get("", response_model=WorldGraphResponse)
async def get_world_graph(
    db: SessionDep,
    storage: StorageDep,
    episode_slug: str = Query(
        ..., description="Slug of the episode the reader is currently in."
    ),
    page: int = Query(
        ..., ge=1, description="1-indexed current page within the episode."
    ),
) -> WorldGraphResponse:
    """GET /api/world-graph — spoiler-filtered slice of the world graph.

    The response contains every entity whose `(episode_debut, page_debut)`
    is at or before the reader's current `(episode_number, page)`, plus
    every relationship whose own debut is at or before the cursor AND
    whose source and target endpoints are both in the visible set.
    """
    episode = await db.scalar(
        select(Episode).where(Episode.slug == episode_slug)
    )
    if episode is None:
        raise HTTPException(
            status_code=404, detail=f"Episode '{episode_slug}' not found"
        )

    page_count = (
        await db.scalar(select(func.count(Page.id)).where(Page.episode_id == episode.id))
    ) or 0
    # Clamp into [1, page_count]. If the episode has no pages yet, treat as
    # page 1 — there's nothing to spoil and the caller likely wants a preview
    # of the (1, 1)-debuting nodes.
    upper = max(page_count, 1)
    clamped = max(1, min(page, upper))
    cursor = (episode.episode_number, clamped)

    entities, relationships = await _spoiler_filtered_subset(db, cursor=cursor)

    nodes: list[WorldNode] = []
    for entity in entities:
        image_url = (
            await storage.url_for(entity.image_url) if entity.image_url else None
        )
        nodes.append(
            WorldNode(
                id=entity.id,
                slug=entity.slug,
                name=entity.name,
                kind=entity.kind,
                summary=entity.summary,
                image_url=image_url,
                x=entity.layout_x,
                y=entity.layout_y,
                episode_debut=entity.episode_debut,
                page_debut=entity.page_debut,
            )
        )

    edges = [
        WorldEdge(
            id=rel.id,
            source=rel.source_id,
            target=rel.target_id,
            kind=rel.kind,
            summary=rel.summary,
            episode_debut=rel.episode_debut,
            page_debut=rel.page_debut,
        )
        for rel in relationships
    ]

    return WorldGraphResponse(nodes=nodes, edges=edges)


async def _spoiler_filtered_subset(
    db: AsyncSession, *, cursor: tuple[int, int]
) -> tuple[list[WorldEntity], list[WorldRelationship]]:
    """Every spoiler-safe entity + every spoiler-safe edge between them.

    Postgres supports row-value comparison directly:
        (episode_debut, page_debut) <= (:ep, :pg)
    SQLAlchemy's `tuple_` builds that expression cleanly. This is the same
    lexicographic shape as Post 6's `_spoiler_filter` (an earlier episode
    at any page, OR this episode at an earlier-or-equal page), expressed
    in row-value form so the SQL reads like the math.

    The both-endpoints-also-visible rule for edges is non-negotiable: an
    edge can carry plot meaning that debuts later than both of its
    endpoints (a rivalry revealed several episodes after the participants
    are introduced). Filter the edge's OWN debut, AND require both
    endpoints to satisfy the same predicate.
    """
    debut_tuple = tuple_(WorldEntity.episode_debut, WorldEntity.page_debut)
    node_stmt = (
        select(WorldEntity)
        .where(debut_tuple <= cursor)
        .order_by(WorldEntity.kind, WorldEntity.slug)
    )
    entities = list((await db.scalars(node_stmt)).all())
    visible_ids = {e.id for e in entities}

    if not visible_ids:
        return entities, []

    edge_debut_tuple = tuple_(
        WorldRelationship.episode_debut, WorldRelationship.page_debut
    )
    edge_stmt = (
        select(WorldRelationship)
        .where(edge_debut_tuple <= cursor)
        .where(WorldRelationship.source_id.in_(visible_ids))
        .where(WorldRelationship.target_id.in_(visible_ids))
        .order_by(WorldRelationship.kind)
    )
    relationships = list((await db.scalars(edge_stmt)).all())
    return entities, relationships
