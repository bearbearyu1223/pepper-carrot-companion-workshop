"""Offline ingestion for the wiki seed (Post 7).

Loads the hand-written articles in `wiki_seed.yaml`, upserts each into the
`wiki_articles` Postgres table (keyed on slug), and embeds one chunk per
article into the `wiki_v1` Chroma collection. This is what makes wiki mode —
and the wiki suggestion chip — return real content.

Usage:
    cd ingestion
    uv run python ingest_wiki.py            # uses wiki_seed.yaml
    uv run python ingest_wiki.py --seed path/to/other.yaml
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import click
import yaml
from chroma_writer import ChromaWriter
from repository import upsert_wiki_article
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.clients import get_embedding_client
from app.config import get_settings
from app.db.models import WikiArticle

logger = logging.getLogger("ingest_wiki")

_DEFAULT_SEED = Path(__file__).parent / "wiki_seed.yaml"


@click.command()
@click.option(
    "--seed",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=str(_DEFAULT_SEED),
    show_default=True,
    help="YAML file of wiki articles to ingest.",
)
def main(seed: Path) -> None:
    """Ingest the wiki seed into Postgres + the wiki_v1 Chroma collection."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(_run(seed))


async def _run(seed_path: Path) -> None:
    settings = get_settings()

    raw = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
    articles_data: list[dict[str, Any]] = raw.get("articles", [])
    if not articles_data:
        raise click.ClickException(f"No articles found in {seed_path}")

    click.echo(f"Ingesting {len(articles_data)} wiki articles from {seed_path}")
    click.echo(f"  embedding: {settings.embedding_provider} ({settings.embedding_model})")

    embedding = get_embedding_client(settings)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    upserted: list[WikiArticle] = []
    try:
        async with session_factory() as session:
            for art in articles_data:
                article = await upsert_wiki_article(
                    session,
                    slug=art["slug"],
                    title=art["title"],
                    content=str(art["content"]).strip(),
                    category=art.get("category"),
                    source_url=art.get("source_url"),
                )
                upserted.append(article)
                click.echo(f"  • {article.slug}")
            await session.commit()
    finally:
        await engine.dispose()

    # Chroma writes after the DB commit so the PKs are durable.
    writer = ChromaWriter(settings.chroma_persist_dir, embedding)
    await writer.upsert_wiki_articles(upserted)

    click.echo("")
    click.echo(f"Done: {len(upserted)} articles → wiki_articles + wiki_v1.")


if __name__ == "__main__":
    main()
