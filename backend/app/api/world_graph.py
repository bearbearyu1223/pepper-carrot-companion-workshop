"""World-graph route — spoiler-filtered entities + relationships (Post 9).

The filter is structural — applied in SQL with row-value comparison so the
runtime never returns nodes or edges past the reader's current page. Same
shape as the page-mode RAG boundary from Post 6: the spoiler integers come
from the URL (validated against the episode's real page count), the model
never sees them, and an edge can only appear if its own debut AND both of
its endpoints' debuts are at or before the reader's cursor.

Two response modes layered on top of the spoiler filter:

- `mode=full` (default, API-stable): every entity and edge whose debut is
  at or before the reader's current spread. Powers the "show me the whole
  world" explorer view.
- `mode=focus`: starts from the canonical characters drawn on the current
  page(s) and expands one hop via the structural edge kinds (`member_of`,
  `lives_in`, `familiar_of`). Surfaces "who's on the page, where they
  belong, and who they live with" without the rest of the universe
  crowding in.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.episodes import get_storage_client
from app.clients import Storage
from app.db.models import (
    Character,
    Episode,
    Page,
    PageCharacter,
    WorldEntity,
    WorldRelationship,
)
from app.db.session import get_session

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[Storage, Depends(get_storage_client)]

Mode = Literal["full", "focus"]

# Edge kinds used to expand the focus seed by one hop. Tuned conservatively
# — "this character + where they belong + who they live with", not the full
# social graph (rivalries, friendships, summons) which would pull in the
# whole universe via Pepper. Tweak this list to broaden the focus view.
_FOCUS_EXPANSION_KINDS = ("member_of", "lives_in", "familiar_of")


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
        ..., ge=1, description="1-indexed left page within the episode."
    ),
    right_page: int | None = Query(
        None,
        ge=1,
        description=(
            "When the reader sees a two-page spread, the right page of that "
            "spread. Defaults to `page` (single-page mode). The spoiler "
            "cursor uses the rightmost visible page; focus mode seeds from "
            "every page in [page, right_page]."
        ),
    ),
    mode: Annotated[
        Mode,
        Query(
            description=(
                "'full' returns every spoiler-safe entity (default, "
                "API-stable). 'focus' returns only on-page characters + "
                "their 1-hop structural neighbors (coven, home, familiar)."
            ),
        ),
    ] = "full",
) -> WorldGraphResponse:
    """GET /api/world-graph — spoiler-filtered slice of the world graph."""
    episode = await db.scalar(
        select(Episode).where(Episode.slug == episode_slug)
    )
    if episode is None:
        raise HTTPException(
            status_code=404, detail=f"Episode '{episode_slug}' not found"
        )

    page_count = (
        await db.scalar(
            select(func.count(Page.id)).where(Page.episode_id == episode.id)
        )
    ) or 0
    # Clamp into [1, page_count]. If the episode has no pages yet, treat as
    # page 1 — there's nothing to spoil and the caller likely wants a preview
    # of the (1, 1)-debuting nodes.
    upper = max(page_count, 1)
    clamped_left = max(1, min(page, upper))
    # Default right_page to the left page (single-page mode). Tolerate
    # callers that send right_page < page by collapsing silently — the URL
    # comes off a flipbook callback and a transient ordering glitch
    # shouldn't 400 the response.
    raw_right = right_page if right_page is not None else clamped_left
    clamped_right = max(clamped_left, max(1, min(raw_right, upper)))
    # The spoiler cursor uses the rightmost visible page — the latest
    # content the reader has seen.
    cursor = (episode.episode_number, clamped_right)

    if mode == "focus":
        entities, relationships = await _focus_subset(
            db,
            episode_id=episode.id,
            left_page=clamped_left,
            right_page=clamped_right,
            cursor=cursor,
        )
    else:
        entities, relationships = await _full_subset(db, cursor=cursor)

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


# ─── Mode implementations ────────────────────────────────────────────────


async def _full_subset(
    db: AsyncSession, *, cursor: tuple[int, int]
) -> tuple[list[WorldEntity], list[WorldRelationship]]:
    """Every spoiler-safe entity + every spoiler-safe edge between them.

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


async def _focus_subset(
    db: AsyncSession,
    *,
    episode_id: UUID,
    left_page: int,
    right_page: int,
    cursor: tuple[int, int],
) -> tuple[list[WorldEntity], list[WorldRelationship]]:
    """On-spread characters + 1-hop expansion via structural edge kinds.

    The seed is the union of canonical characters drawn on every page in
    `[left_page, right_page]` — single-page mode passes the same value
    for both; two-page-spread landscape mode passes the spread bounds.
    We then expand one hop via the structural edge kinds (`member_of`,
    `lives_in`, `familiar_of`) so the reader sees who's on the page,
    where they belong, and who they live with.

    Falls back to the full subset when the spread has no canonical
    characters (e.g. an SFX-only panel, a landscape painting, or pages
    that haven't been ingested yet) — better to show the world than to
    show an empty panel.
    """
    debut_tuple = tuple_(WorldEntity.episode_debut, WorldEntity.page_debut)
    edge_debut_tuple = tuple_(
        WorldRelationship.episode_debut, WorldRelationship.page_debut
    )

    # 1. Characters drawn on any page in the spread → world_entity rows
    #    (joined via character_id). Distinct so a character on both pages
    #    doesn't seed twice. Spoiler filter still applies — a hand-edit
    #    could in principle put a future debut on a world entity that's
    #    also on the page; we never want to leak past the cursor.
    seed_stmt = (
        select(WorldEntity)
        .join(Character, Character.id == WorldEntity.character_id)
        .join(PageCharacter, PageCharacter.character_id == Character.id)
        .join(Page, Page.id == PageCharacter.page_id)
        .where(Page.episode_id == episode_id)
        .where(Page.page_number >= left_page)
        .where(Page.page_number <= right_page)
        .where(debut_tuple <= cursor)
        .distinct()
    )
    seed_entities = list((await db.scalars(seed_stmt)).all())

    if not seed_entities:
        # No canonical characters on the spread (or the pages haven't
        # been ingested). Show the spoiler-filtered world rather than an
        # empty panel — most readers' next action is "ok then show me
        # everything anyway", and the kind-filter bar is right there.
        return await _full_subset(db, cursor=cursor)

    seed_ids = {e.id for e in seed_entities}

    # 2. One-hop expansion via the structural edge kinds. Edges still
    #    have to be spoiler-visible — if the godmother_of relation debuts
    #    at ep11 and the reader is on ep10, neither the edge nor any
    #    2nd-tier expansion should leak.
    expansion_stmt = (
        select(WorldRelationship)
        .where(edge_debut_tuple <= cursor)
        .where(WorldRelationship.kind.in_(_FOCUS_EXPANSION_KINDS))
        .where(
            or_(
                WorldRelationship.source_id.in_(seed_ids),
                WorldRelationship.target_id.in_(seed_ids),
            )
        )
    )
    expansion_edges = list((await db.scalars(expansion_stmt)).all())

    visible_ids: set[UUID] = set(seed_ids)
    for edge in expansion_edges:
        if edge.source_id in seed_ids:
            visible_ids.add(edge.target_id)
        if edge.target_id in seed_ids:
            visible_ids.add(edge.source_id)

    # 3. Fetch the full entity rows for the expanded set, applying the
    #    spoiler filter once more as defense-in-depth.
    entities_stmt = (
        select(WorldEntity)
        .where(WorldEntity.id.in_(visible_ids))
        .where(debut_tuple <= cursor)
        .order_by(WorldEntity.kind, WorldEntity.slug)
    )
    entities = list((await db.scalars(entities_stmt)).all())
    final_visible_ids = {e.id for e in entities}

    # 4. Edges among the visible set. Return ALL spoiler-safe edges among
    #    these nodes (not just the structural-expansion kinds) so that,
    #    e.g., a rivalry between two members of the focus subset still
    #    shows when both participants are in it.
    edges_stmt = (
        select(WorldRelationship)
        .where(edge_debut_tuple <= cursor)
        .where(WorldRelationship.source_id.in_(final_visible_ids))
        .where(WorldRelationship.target_id.in_(final_visible_ids))
        .order_by(WorldRelationship.kind)
    )
    relationships = list((await db.scalars(edges_stmt)).all())
    return entities, relationships
