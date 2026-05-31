"""Offline wiki ingestion (Post 9 — summary-first architecture).

Reads markdown summaries with YAML frontmatter from two parallel
directories — `data/wiki-summaries/entities/` (one per world-graph
entity) and `data/wiki-summaries/topics/` (a handful of non-entity lore
summaries) — validates them through `WikiArticleData`, upserts each
into the `wiki_articles` Postgres table (keyed on slug), and embeds
each summary as a single document into the `wiki_v1` Chroma collection.

The summaries are authored by the `summarize-wiki` Claude Code skill
from the raw upstream wiki (`data/raw/wiki-upstream/`) and the curated
bios (`data/raw/wiki/`). Embedding focused ~150-word summaries instead
of 30 KB multi-entity articles is what makes top-3 wiki retrieval land
small enough context that Post 8's OUTPUT RULES actually hold against
qwen2.5:7b. The architectural rationale lives in Post 9 of the blog
series and in `.claude/skills/summarize-wiki/SKILL.md`.

Idempotent: re-running picks up edits and new summaries without
duplicating rows. Either directory missing is fine — passing `--topics
""` skips topics entirely. Pointing at the raw directories
(`--entities ../data/raw/wiki --topics ../data/raw/wiki-upstream`)
still works for debugging, but is not the supported chat path.

Usage:
    cd ingestion
    uv run python ingest_wiki.py
    uv run python ingest_wiki.py \\
        --entities ../data/wiki-summaries/entities \\
        --topics ../data/wiki-summaries/topics
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click
from chroma_writer import ChromaWriter
from repository import upsert_wiki_article
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from wiki_loader import WikiArticleData, load_wiki_articles

from app.clients import get_embedding_client
from app.config import get_settings
from app.db.models import WikiArticle

logger = logging.getLogger("ingest_wiki")

_DEFAULT_ENTITIES = (
    Path(__file__).parent.parent / "data" / "wiki-summaries" / "entities"
)
_DEFAULT_TOPICS = Path(__file__).parent.parent / "data" / "wiki-summaries" / "topics"


@click.command()
@click.option(
    "--entities",
    type=click.Path(file_okay=False, path_type=Path),
    default=str(_DEFAULT_ENTITIES),
    show_default=True,
    help="Directory of per-entity wiki summary .md files.",
)
@click.option(
    "--topics",
    type=click.Path(file_okay=False, path_type=Path),
    default=str(_DEFAULT_TOPICS),
    show_default=True,
    help="Directory of non-entity topic summary .md files.",
)
def main(entities: Path, topics: Path) -> None:
    """Ingest the wiki summaries into Postgres + the wiki_v1 Chroma collection."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(_run(entities, topics))


async def _run(entities: Path, topics: Path) -> None:
    settings = get_settings()

    articles: list[WikiArticleData] = []
    if entities.is_dir():
        entity_articles = load_wiki_articles(entities)
        click.echo(f"Loaded {len(entity_articles)} entity summaries from {entities}")
        articles.extend(entity_articles)
    else:
        click.echo(
            f"(skipped: {entities} does not exist — "
            "run the `summarize-wiki` Claude Code skill to populate it)"
        )

    if topics.is_dir():
        topic_articles = load_wiki_articles(topics)
        click.echo(f"Loaded {len(topic_articles)} topic summaries from {topics}")
        articles.extend(topic_articles)
    else:
        click.echo(f"(skipped: {topics} does not exist)")

    if not articles:
        raise click.ClickException(
            "No wiki summaries found in either directory. Run the "
            "`summarize-wiki` skill (or point --entities/--topics at "
            "directories that exist)."
        )

    # Cross-corpus uniqueness: a slug appearing in both directories would be a
    # bug — entity slugs and topic slugs are disjoint by convention (entities
    # match world-graph entity slugs; topics use lore-overview names).
    seen: set[str] = set()
    for a in articles:
        if a.slug in seen:
            raise click.ClickException(
                f"Duplicate wiki slug '{a.slug}' across entities + topics "
                f"({a.source_path})."
            )
        seen.add(a.slug)

    click.echo("")
    click.echo(f"Ingesting {len(articles)} summaries total.")
    click.echo(
        f"  embedding: {settings.embedding_provider} ({settings.embedding_model})"
    )

    embedding = get_embedding_client(settings)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    upserted: list[WikiArticle] = []
    try:
        async with session_factory() as session:
            for art in articles:
                article = await upsert_wiki_article(
                    session,
                    slug=art.slug,
                    title=art.title,
                    content=art.content,
                    category=art.category,
                    source_url=art.source_url,
                )
                upserted.append(article)
                click.echo(
                    f"  • {article.slug:<32} ({art.category or 'uncategorized'})"
                )
            await session.commit()
    finally:
        await engine.dispose()

    # Chroma writes after the DB commit so the PKs are durable.
    writer = ChromaWriter(settings.chroma_persist_dir, embedding)
    await writer.upsert_wiki_articles(upserted)

    click.echo("")
    click.echo(f"Done: {len(upserted)} summaries → wiki_articles + wiki_v1.")


if __name__ == "__main__":
    main()
