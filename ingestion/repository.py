"""Async DB write helpers for the offline ingestion pipeline.

Workshop-starter scope: episode ingestion only. Each function performs one
logical upsert on an `AsyncSession` and flushes so the row's PK is available,
but does NOT commit — the caller decides where the transaction boundary is.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID

from episode_loader import EpisodeMetadata
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from world_graph_loader import EntityData, RelationshipData

from app.clients.vision import PageDescription
from app.db.models import (
    Character,
    Episode,
    Page,
    PageCharacter,
    WikiArticle,
    WorldEntity,
    WorldRelationship,
)

logger = logging.getLogger(__name__)


class PageImageKeys(TypedDict):
    """Relative storage keys for the three page-image variants.

    Keys are the relative paths the storage abstraction returns from `put`,
    not full URLs (see CLAUDE.md convention #5).
    """

    display: str
    thumbnail: str
    original: str


async def upsert_episode(session: AsyncSession, metadata: EpisodeMetadata) -> Episode:
    """Insert-or-update the episode row keyed on `slug`.

    Mutates only metadata-derived fields. Does NOT touch `cover_image_url` or
    `plot_summary` — those are written separately as the pipeline progresses.
    """
    existing = await session.scalar(select(Episode).where(Episode.slug == metadata.slug))
    published_dt = datetime.combine(metadata.published_at, datetime.min.time(), tzinfo=UTC)

    if existing is None:
        episode = Episode(
            slug=metadata.slug,
            title=metadata.title,
            episode_number=metadata.episode_number,
            language=metadata.language,
            credits_url=metadata.credits_url,
            published_at=published_dt,
        )
        session.add(episode)
    else:
        existing.title = metadata.title
        existing.episode_number = metadata.episode_number
        existing.language = metadata.language
        existing.credits_url = metadata.credits_url
        existing.published_at = published_dt
        episode = existing

    await session.flush()
    return episode


async def upsert_page(
    session: AsyncSession,
    episode_id: UUID,
    page_number: int,
    image_keys: PageImageKeys,
    description: PageDescription,
) -> Page:
    """Insert-or-update one page row keyed on `(episode_id, page_number)`.

    Replaces the description-derived fields wholesale on each call so re-running
    the pipeline picks up new prompt outputs without manual cleanup.
    """
    existing = await session.scalar(
        select(Page).where(
            Page.episode_id == episode_id,
            Page.page_number == page_number,
        )
    )
    ocr_text = _flatten_dialogue(description)

    if existing is None:
        page = Page(
            episode_id=episode_id,
            page_number=page_number,
            image_url=image_keys["display"],
            thumbnail_url=image_keys["thumbnail"],
            original_url=image_keys["original"],
            visual_description=description.visual_description,
            ocr_text=ocr_text,
            mood_tags=list(description.mood_tags),
        )
        session.add(page)
    else:
        existing.image_url = image_keys["display"]
        existing.thumbnail_url = image_keys["thumbnail"]
        existing.original_url = image_keys["original"]
        existing.visual_description = description.visual_description
        existing.ocr_text = ocr_text
        existing.mood_tags = list(description.mood_tags)
        page = existing

    await session.flush()
    return page


async def link_page_characters(
    session: AsyncSession,
    page_id: UUID,
    character_names: list[str],
) -> None:
    """Replace the page's character associations with the given names.

    Unknown names (not in the `characters` table) are warned and skipped — we'd
    rather flag for human review than fail the whole ingestion run.
    """
    if character_names:
        rows = await session.scalars(
            select(Character).where(Character.name.in_(character_names))
        )
        found = {c.name: c.id for c in rows}
    else:
        found = {}

    unknown = [n for n in character_names if n not in found]
    if unknown:
        logger.warning(
            "page %s: unknown character names (skipping): %s",
            page_id,
            ", ".join(sorted(set(unknown))),
        )

    existing_links = await session.scalars(
        select(PageCharacter).where(PageCharacter.page_id == page_id)
    )
    for link in existing_links:
        await session.delete(link)
    await session.flush()

    for character_id in found.values():
        session.add(PageCharacter(page_id=page_id, character_id=character_id))
    await session.flush()


async def upsert_wiki_article(
    session: AsyncSession,
    *,
    slug: str,
    title: str,
    content: str,
    category: str | None = None,
    source_url: str | None = None,
) -> WikiArticle:
    """Insert-or-update one wiki article keyed on `slug` (Post 7).

    Replaces title/content/category/source_url wholesale on each call so
    editing `wiki_seed.yaml` and re-running picks up the change.
    """
    existing = await session.scalar(select(WikiArticle).where(WikiArticle.slug == slug))
    if existing is None:
        article = WikiArticle(
            slug=slug,
            title=title,
            content=content,
            category=category,
            source_url=source_url,
        )
        session.add(article)
    else:
        existing.title = title
        existing.content = content
        existing.category = category
        existing.source_url = source_url
        article = existing
    await session.flush()
    return article


async def upsert_episode_summary(
    session: AsyncSession, episode_id: UUID, summary: str
) -> None:
    """Set the episode's plot_summary. Used after all pages have been described."""
    episode = await session.get(Episode, episode_id)
    if episode is None:
        raise LookupError(f"No episode with id {episode_id}")
    episode.plot_summary = summary
    await session.flush()


async def upsert_world_entity(
    session: AsyncSession,
    data: EntityData,
) -> WorldEntity:
    """Insert-or-update one world-graph entity row keyed on `slug`.

    If `character_slug` is set, looks up the matching `characters` row by
    name (lower-cased compare) and links via `character_id`. An unknown
    `character_slug` is logged but not fatal — the entity still upserts so
    the YAML can be authored before the canonical roster catches up.
    """
    existing = await session.scalar(
        select(WorldEntity).where(WorldEntity.slug == data.slug)
    )

    character_id: UUID | None = None
    if data.character_slug:
        character_id = await _resolve_character_id(session, data.character_slug)
        if character_id is None:
            logger.warning(
                "world entity '%s' references unknown character_slug '%s' — "
                "leaving character_id NULL",
                data.slug,
                data.character_slug,
            )

    if existing is None:
        entity = WorldEntity(
            slug=data.slug,
            name=data.name,
            kind=data.kind,
            summary=data.summary,
            image_url=data.image_url,
            episode_debut=data.episode_debut,
            page_debut=data.page_debut,
            layout_x=data.layout_x,
            layout_y=data.layout_y,
            character_id=character_id,
        )
        session.add(entity)
    else:
        existing.name = data.name
        existing.kind = data.kind
        existing.summary = data.summary
        existing.image_url = data.image_url
        existing.episode_debut = data.episode_debut
        existing.page_debut = data.page_debut
        existing.layout_x = data.layout_x
        existing.layout_y = data.layout_y
        existing.character_id = character_id
        entity = existing

    await session.flush()
    return entity


async def upsert_world_relationship(
    session: AsyncSession,
    data: RelationshipData,
    slug_to_id: dict[str, UUID],
) -> WorldRelationship:
    """Insert-or-update one relationship row keyed on (source_id, target_id, kind).

    The unique constraint `uq_world_relationships_src_tgt_kind` enforces the
    same triple in SQL; this helper finds the existing row by the same
    columns and mutates it in place if present.
    """
    source_id = slug_to_id[data.source]
    target_id = slug_to_id[data.target]

    existing = await session.scalar(
        select(WorldRelationship).where(
            WorldRelationship.source_id == source_id,
            WorldRelationship.target_id == target_id,
            WorldRelationship.kind == data.kind,
        )
    )

    if existing is None:
        rel = WorldRelationship(
            source_id=source_id,
            target_id=target_id,
            kind=data.kind,
            summary=data.summary,
            episode_debut=data.episode_debut,
            page_debut=data.page_debut,
        )
        session.add(rel)
    else:
        existing.summary = data.summary
        existing.episode_debut = data.episode_debut
        existing.page_debut = data.page_debut
        rel = existing

    await session.flush()
    return rel


async def _resolve_character_id(
    session: AsyncSession, character_slug: str
) -> UUID | None:
    """Lower-case match against the seeded characters table."""
    target = character_slug.strip().lower()
    rows = await session.scalars(select(Character))
    for character in rows:
        if character.name.lower() == target:
            return character.id
    return None


def _flatten_dialogue(description: PageDescription) -> str | None:
    """Render the structured dialogue back into a single OCR-text blob.

    Stored on `pages.ocr_text` so a future BM25 hybrid retriever can search
    spoken lines without re-parsing the description payload.
    """
    if not description.dialogue:
        return None
    parts: list[str] = []
    for line in description.dialogue:
        if line.speaker:
            parts.append(f"{line.speaker}: {line.text}")
        else:
            parts.append(line.text)
    return "\n".join(parts)
