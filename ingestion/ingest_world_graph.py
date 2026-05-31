"""Offline ingestion for the world-graph YAML pair (Post 9).

Reads the hand-authored or skill-extracted YAML at
`data/world-graph/{entities,relationships}.yaml`, validates it through the
loader's pydantic contract, and upserts every entity + relationship into
Postgres. Idempotent — re-running picks up edits, never duplicates.

The YAML is the durable artifact. The `extract-world-graph` Claude Code
skill is a one-shot author; once the YAML is good, fixes go straight into
the YAML and you re-run this loader (~1s per run on the workshop's small
graph). See `docs/decisions/0005-skill-driven-world-graph.md`.

Usage:
    cd ingestion
    uv run python ingest_world_graph.py                # uses ../data/world-graph
    uv run python ingest_world_graph.py --source path/to/dir
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click
from repository import upsert_world_entity, upsert_world_relationship
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from world_graph_loader import load_world_graph

from app.config import get_settings
from app.db.models import WorldEntity, WorldRelationship

logger = logging.getLogger("ingest_world_graph")

_DEFAULT_SOURCE = Path(__file__).parent.parent / "data" / "world-graph"


@click.command()
@click.option(
    "--source",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=str(_DEFAULT_SOURCE),
    show_default=True,
    help="Directory holding entities.yaml + relationships.yaml.",
)
def main(source: Path) -> None:
    """Validate and upsert the world-graph YAML pair into Postgres."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(_run(source))


async def _run(source: Path) -> None:
    settings = get_settings()

    entities, relationships = load_world_graph(source)
    click.echo(
        f"Loaded {len(entities)} entities and {len(relationships)} "
        f"relationships from {source}"
    )

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    yaml_slugs = {e.slug for e in entities}

    try:
        async with session_factory() as session:
            # Relationships first: blanket delete-then-insert. The YAML is the
            # source of truth, so an edge removed from the YAML must disappear
            # from the DB on the next ingest. The unique constraint on
            # (source_id, target_id, kind) means the upsert helper handles
            # the insert side; we wipe first to handle the "edge removed"
            # case AND to clear the FK that would block the orphan-entity
            # delete below.
            await session.execute(delete(WorldRelationship))
            await session.flush()

            # Orphan entities: anything in the DB whose slug isn't in the
            # current YAML is no-longer-canonical and must be deleted. The
            # YAML is the source of truth for entities too — same discipline
            # as relationships. Without this, a renamed slug leaves the old
            # row sitting in the graph forever (e.g. `squirrels-end` after
            # a rename to `squirrel-s-end`), which then appears as a ghost
            # duplicate node with broken-looking edges in the frontend.
            db_slugs = (
                await session.scalars(select(WorldEntity.slug))
            ).all()
            orphan_slugs = [s for s in db_slugs if s not in yaml_slugs]
            if orphan_slugs:
                await session.execute(
                    delete(WorldEntity).where(WorldEntity.slug.in_(orphan_slugs))
                )
                await session.flush()
                click.echo(
                    f"  ✕ pruned {len(orphan_slugs)} orphan entit"
                    f"{'y' if len(orphan_slugs) == 1 else 'ies'}: "
                    f"{', '.join(sorted(orphan_slugs))}"
                )

            # Entities: upsert by slug. Existing rows are mutated in place so
            # FKs (character_id) stay stable across re-runs.
            slug_to_id: dict[str, object] = {}
            for entity_data in entities:
                entity = await upsert_world_entity(session, entity_data)
                slug_to_id[entity_data.slug] = entity.id
                click.echo(f"  • entity   {entity_data.slug:<20} ({entity_data.kind})")

            for rel_data in relationships:
                await upsert_world_relationship(session, rel_data, slug_to_id)  # type: ignore[arg-type]
                click.echo(
                    f"  • edge     {rel_data.source} --{rel_data.kind}--> {rel_data.target}"
                )

            await session.commit()
    finally:
        await engine.dispose()

    click.echo("")
    click.echo(
        f"Done: {len(entities)} entities + {len(relationships)} relationships "
        "upserted into world_entities + world_relationships."
    )


if __name__ == "__main__":
    main()
