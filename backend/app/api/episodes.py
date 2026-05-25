"""Episode routes: list and detail.

Two endpoints back the read-only reading UI built in Post 5:
- `GET /api/episodes` — list of episodes for the picker grid.
- `GET /api/episodes/{slug}` — full episode detail including every page,
  with `image_url` already resolved to an absolute URL by the storage
  abstraction.

CLAUDE.md rule 5: image URLs in the database are relative keys; the full URL
is composed at API response time through `Storage.url_for()`. Swapping
storage backends (local → R2) is a config change, not a migration. The
resolution loop in this file is the place where that pays off — search for
`storage.url_for(` to find every call site.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import Storage, get_storage
from app.config import Settings, get_settings
from app.db.models import Episode, Page
from app.db.session import get_session

router = APIRouter()


def get_storage_client(settings: Annotated[Settings, Depends(get_settings)]) -> Storage:
    """Build the configured storage client.

    Wrapped as a FastAPI dependency so route handlers never import storage
    backends directly and tests can override it via app.dependency_overrides.
    """
    return get_storage(settings)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[Storage, Depends(get_storage_client)]


def _summary_for_card(text: str | None) -> str | None:
    """Return the full plot summary for a picker card.

    No truncation — the picker shows the entire summary so the user can
    decide if they want to read the episode. Card heights vary across the
    grid as a result, which is fine: CSS grid handles uneven row heights
    without breaking layout.
    """
    if text is None:
        return None
    cleaned = text.strip()
    return cleaned or None


# ─────────────────────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────────────────────


class EpisodeListItem(BaseModel):
    id: UUID
    slug: str
    title: str
    episode_number: int
    cover_image_url: str | None
    page_count: int
    plot_summary: str | None


class EpisodeListResponse(BaseModel):
    episodes: list[EpisodeListItem]


class CharacterSummary(BaseModel):
    id: UUID
    name: str
    image_url: str | None


class PageCharacterRef(BaseModel):
    id: UUID
    name: str


class PageDetail(BaseModel):
    id: UUID
    page_number: int
    image_url: str
    thumbnail_url: str | None
    image_metadata: dict[str, Any]
    characters: list[PageCharacterRef]


class EpisodeDetail(BaseModel):
    id: UUID
    slug: str
    title: str
    episode_number: int
    plot_summary: str | None
    credits_url: str | None
    characters: list[CharacterSummary]
    pages: list[PageDetail]


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────


@router.get("", response_model=EpisodeListResponse)
async def list_episodes(db: SessionDep, storage: StorageDep) -> EpisodeListResponse:
    """GET /api/episodes — list of episodes for the picker."""
    page_counts = (
        select(Page.episode_id, func.count(Page.id).label("page_count"))
        .group_by(Page.episode_id)
        .subquery()
    )
    stmt = (
        select(Episode, func.coalesce(page_counts.c.page_count, 0).label("page_count"))
        .outerjoin(page_counts, Episode.id == page_counts.c.episode_id)
        .order_by(Episode.episode_number.asc())
    )
    rows = (await db.execute(stmt)).all()

    items: list[EpisodeListItem] = []
    for episode, page_count in rows:
        cover_url = (
            await storage.url_for(episode.cover_image_url)
            if episode.cover_image_url
            else None
        )
        items.append(
            EpisodeListItem(
                id=episode.id,
                slug=episode.slug,
                title=episode.title,
                episode_number=episode.episode_number,
                cover_image_url=cover_url,
                page_count=int(page_count),
                plot_summary=_summary_for_card(episode.plot_summary),
            )
        )
    return EpisodeListResponse(episodes=items)


@router.get("/{slug}", response_model=EpisodeDetail)
async def get_episode(slug: str, db: SessionDep, storage: StorageDep) -> EpisodeDetail:
    """GET /api/episodes/{slug} — full episode detail with pages."""
    stmt = (
        select(Episode)
        .where(Episode.slug == slug)
        .options(selectinload(Episode.pages).selectinload(Page.characters))
    )
    episode = (await db.execute(stmt)).scalar_one_or_none()
    if episode is None:
        raise HTTPException(status_code=404, detail=f"Episode '{slug}' not found")

    # Episode-level character roster: union across all pages of this episode,
    # deduped by id, sorted by name for stable output.
    seen_char_ids: set[UUID] = set()
    episode_characters: list[CharacterSummary] = []
    for page in episode.pages:
        for char in page.characters:
            if char.id in seen_char_ids:
                continue
            seen_char_ids.add(char.id)
            char_image = (
                await storage.url_for(char.image_url) if char.image_url else None
            )
            episode_characters.append(
                CharacterSummary(id=char.id, name=char.name, image_url=char_image)
            )
    episode_characters.sort(key=lambda c: c.name)

    pages: list[PageDetail] = []
    for page in episode.pages:
        image_url = await storage.url_for(page.image_url)
        thumbnail_url = (
            await storage.url_for(page.thumbnail_url) if page.thumbnail_url else None
        )
        pages.append(
            PageDetail(
                id=page.id,
                page_number=page.page_number,
                image_url=image_url,
                thumbnail_url=thumbnail_url,
                image_metadata=page.image_metadata or {},
                characters=[
                    PageCharacterRef(id=c.id, name=c.name) for c in page.characters
                ],
            )
        )

    return EpisodeDetail(
        id=episode.id,
        slug=episode.slug,
        title=episode.title,
        episode_number=episode.episode_number,
        plot_summary=episode.plot_summary,
        credits_url=episode.credits_url,
        characters=episode_characters,
        pages=pages,
    )
