"""Offline ingestion pipeline for one episode.

Workshop-starter scope: episode ingestion only. Wiki and world-graph
ingestion paths land in later posts and live in the full project repo.

Usage:
    cd ingestion
    uv run python ingest.py --episode-dir ../data/raw/ep01-potion-of-flight
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from datetime import UTC, datetime
from pathlib import Path

import click
from chroma_writer import ChromaWriter
from episode_loader import EpisodeMetadata, list_page_files, load_episode_metadata
from images import ProcessedPageImages, process_page_image
from repository import (
    PageImageKeys,
    link_page_characters,
    upsert_episode,
    upsert_episode_summary,
    upsert_page,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from tqdm import tqdm

from app.clients import (
    ChatClient,
    Storage,
    VisionClient,
    get_chat_client,
    get_embedding_client,
    get_storage,
    get_vision_client,
)
from app.clients.chat import ContentBlockText, Message
from app.clients.vision import PageDescription
from app.config import get_settings
from app.db.models import Character, Episode

logger = logging.getLogger("ingest")


@click.command()
@click.option(
    "--episode-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to a directory containing one episode's raw assets.",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def main(episode_dir: Path, verbose: bool) -> None:
    """Ingest one episode of Pepper&Carrot into the system."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(_run_episode(episode_dir))


async def _run_episode(episode_dir: Path) -> None:
    """Ingest one episode end-to-end. See Post 4 for the design walkthrough."""
    settings = get_settings()

    # Step 1: validate input — load metadata + page list before opening any
    # external connections, so a malformed input fails fast with a clear error.
    metadata = load_episode_metadata(episode_dir)
    page_files = list_page_files(episode_dir)
    if not page_files:
        raise click.ClickException(f"No page files found in {episode_dir}/pages/")

    # Build clients (the one place we wire up SDKs — see CLAUDE.md rule #1).
    vision = get_vision_client(settings)
    embedding = get_embedding_client(settings)
    storage = get_storage(settings)
    chat = get_chat_client(settings)

    click.echo(f"Ingesting {metadata.slug} ({len(page_files)} pages) from: {episode_dir}")
    click.echo(f"  vision: {settings.vision_provider} (sibling .json next to each page)")
    click.echo(f"  embedding: {settings.embedding_provider} ({settings.embedding_model})")
    click.echo(f"  storage: {settings.storage_backend}")
    click.echo(f"  database: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")

    # Per-page commits so the long Ollama waits don't hold a transaction open.
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    page_results: list[tuple[object, PageDescription]] = []
    episode_slug: str | None = None
    try:
        click.echo("Connecting to database…", nl=False)
        async with session_factory() as session:
            click.echo(" connected.")
            try:
                click.echo("Upserting episode row…", nl=False)
                episode = await upsert_episode(session, metadata)
                episode_id = episode.id
                episode_slug = episode.slug
                await session.commit()
                click.echo(f" id={episode_id}")

                click.echo("Loading cast list…", nl=False)
                cast_list = await _load_cast_list(session)
                click.echo(f" {len(cast_list)} characters.")
                if not cast_list:
                    logger.warning(
                        "No characters seeded yet — character_present hints will all "
                        "be flagged unknown. Run `uv run python -m app.db.seed` first."
                    )

                # Optional cover image
                if metadata.cover_filename:
                    cover_key = await _process_cover_image(
                        episode_dir=episode_dir,
                        cover_filename=metadata.cover_filename,
                        episode_slug=episode_slug,
                        storage=storage,
                    )
                    if cover_key is not None:
                        ep = await session.get(Episode, episode_id)
                        assert ep is not None
                        ep.cover_image_url = cover_key
                        await session.commit()
                        click.echo(f"Cover uploaded → {cover_key}")

                # Per-page processing
                previous_desc: str | None = None
                progress = tqdm(page_files, desc="pages", unit="page")
                for page_num, page_file in enumerate(progress, start=1):
                    click.echo(f"[{page_num}/{len(page_files)}] {page_file.name} …")
                    page, description = await _process_one_page(
                        session=session,
                        storage=storage,
                        vision=vision,
                        episode_id=episode_id,
                        episode_slug=episode_slug,
                        page_number=page_num,
                        page_file=page_file,
                        previous_visual_description=previous_desc,
                        cast_list=cast_list,
                    )
                    await session.commit()
                    page_results.append((page, description))
                    previous_desc = description.visual_description
                    click.echo(
                        f"    → {len(description.dialogue)} dialogue lines, "
                        f"chars={description.characters_present}"
                    )

                # Episode plot summary (best-effort)
                try:
                    summary = await _summarize_episode(
                        chat, [d for _, d in page_results], metadata
                    )
                    await upsert_episode_summary(session, episode_id, summary)
                    await session.commit()
                    click.echo(
                        f"  plot summary: {summary[:120]}{'…' if len(summary) > 120 else ''}"
                    )
                except NotImplementedError:
                    logger.warning(
                        "Chat client not implemented for provider=%s. "
                        "Skipping plot summary; episode.plot_summary stays NULL.",
                        settings.chat_provider,
                    )
                except Exception as exc:
                    logger.warning("Plot summary failed (continuing): %s", exc)

                # Refresh ingested_at and commit one last time.
                ep_stamp = await session.get(Episode, episode_id)
                assert ep_stamp is not None
                ep_stamp.ingested_at = datetime.now(UTC)
                await session.commit()
            except BaseException:
                logger.warning("Ingestion aborted — rolling back DB transaction.")
                try:
                    await session.rollback()
                except Exception:
                    logger.exception("Rollback also failed")
                raise
    finally:
        await engine.dispose()

    # Chroma writes (after DB commit so PKs are durable on disk)
    chroma_writer = ChromaWriter(settings.chroma_persist_dir, embedding)
    await chroma_writer.upsert_page_chunks(
        page_results,  # type: ignore[arg-type]
        episode_number=metadata.episode_number,
    )

    click.echo("")
    click.echo(f"Done: {episode_slug}")
    click.echo(f"  pages ingested: {len(page_results)}")
    click.echo(f"  pages_v1 chunks written: {len(page_results)}")


async def _process_cover_image(
    *,
    episode_dir: Path,
    cover_filename: str,
    episode_slug: str,
    storage: Storage,
) -> str | None:
    """Process and upload an episode cover. Returns the display variant key for
    `episodes.cover_image_url`, or None if the cover file isn't on disk.
    """
    cover_path = episode_dir / cover_filename
    if not cover_path.is_file():
        logger.warning("Cover declared in metadata but missing on disk: %s", cover_path)
        return None

    processed = process_page_image(cover_path)
    base_key = f"episodes/{episode_slug}/cover"
    display_key = f"{base_key}-display.webp"
    thumbnail_key = f"{base_key}-thumbnail.webp"
    original_ext = cover_path.suffix.lower() or ".jpg"
    original_key = f"{base_key}-original{original_ext}"
    original_mime = mimetypes.guess_type(cover_path.name)[0] or "application/octet-stream"

    await storage.put(display_key, processed.display_bytes, "image/webp")
    await storage.put(thumbnail_key, processed.thumbnail_bytes, "image/webp")
    await storage.put(original_key, processed.original_bytes, original_mime)
    return display_key


async def _process_one_page(
    *,
    session: AsyncSession,
    storage: Storage,
    vision: VisionClient,
    episode_id: object,
    episode_slug: str,
    page_number: int,
    page_file: Path,
    previous_visual_description: str | None,
    cast_list: list[str],
) -> tuple[object, PageDescription]:
    """Process and upload one page, then upsert its row + character links."""
    # (a) image variants
    processed: ProcessedPageImages = process_page_image(page_file)

    # (b) upload variants. Originals keep their source extension + mime type.
    base_key = f"episodes/{episode_slug}/pages/{page_number:03d}"
    thumbnail_key = f"{base_key}-thumbnail.webp"
    original_ext = page_file.suffix.lower() or ".jpg"
    original_key = f"{base_key}-original{original_ext}"
    original_mime = mimetypes.guess_type(page_file.name)[0] or "application/octet-stream"

    await storage.put(thumbnail_key, processed.thumbnail_bytes, "image/webp")
    await storage.put(original_key, processed.original_bytes, original_mime)

    # Animated sources (GIF) keep their original; the static WebP variant would
    # lose the motion. For everything else, the resized WebP keeps payloads small.
    if processed.is_animated:
        display_key = original_key
    else:
        display_key = f"{base_key}-display.webp"
        await storage.put(display_key, processed.display_bytes, "image/webp")

    # (c) load the page description (sibling .json — written by the skill).
    description = await vision.describe_page(
        image_path=page_file,
        previous_page_description=previous_visual_description,
        cast_list=cast_list,
    )

    # (d) upsert page row
    image_keys: PageImageKeys = {
        "display": display_key,
        "thumbnail": thumbnail_key,
        "original": original_key,
    }
    page = await upsert_page(session, episode_id, page_number, image_keys, description)  # type: ignore[arg-type]

    page.image_metadata = {
        "width": processed.metadata.width,
        "height": processed.metadata.height,
        "blurhash": processed.metadata.blurhash,
        "dominant_color": processed.metadata.dominant_color,
    }
    await session.flush()

    # (e) link characters
    await link_page_characters(session, page.id, list(description.characters_present))

    return page, description


async def _load_cast_list(session: AsyncSession) -> list[str]:
    rows = await session.scalars(select(Character.name).order_by(Character.name))
    return list(rows)


async def _summarize_episode(
    chat: ChatClient,
    descriptions: list[PageDescription],
    metadata: EpisodeMetadata,
) -> str:
    """Ask the chat model for a 2-3 sentence plot summary of the episode."""
    pages_block = "\n\n".join(
        f"Page {i}: {d.visual_description}" for i, d in enumerate(descriptions, start=1)
    )
    user_text = (
        f"Below are the page-by-page descriptions for one episode of the webcomic "
        f"Pepper&Carrot ('{metadata.title}').\n\n"
        f"{pages_block}\n\n"
        "In 2-3 sentences, summarise what happens in this episode. "
        "Plain prose, no bullet points, no preamble."
    )
    system = (
        "You are a literary editor writing concise, spoiler-aware plot summaries "
        "for a children's webcomic."
    )
    messages = [Message(role="user", content=[ContentBlockText(text=user_text)])]
    chunks: list[str] = []
    async for chunk in chat.stream(system=system, messages=messages, max_tokens=200):
        chunks.append(chunk)
    return "".join(chunks).strip()


if __name__ == "__main__":
    main()
