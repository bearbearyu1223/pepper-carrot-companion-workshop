"""Idempotent seed for the canonical Pepper&Carrot character cast.

The VLM ingestion step labels each page's `characters_present` using these names,
and the runtime character-chip UI / "next appearance" navigation joins on them.
Without this seed, `link_page_characters` warn-skips every name the VLM produces
and the page_characters table stays empty.

Run via:
    cd backend && uv run python -m app.db.seed
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Character

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CastEntry:
    name: str
    bio: str
    aliases: list[str] = field(default_factory=list)


# Canonical cast — recurring named characters across the comic. Names are
# sourced from the upstream wiki (data/raw/wiki-upstream/characters.md) so the
# VLM's character labels align with the canonical roster. Aliases are short
# hints for occasional alternative phrasings the VLM might emit.
CANONICAL_CAST: list[_CastEntry] = [
    # ── Main characters ──
    _CastEntry(
        name="Pepper",
        bio="A young witch of the Chaosah school of chaos magic. Protagonist.",
    ),
    _CastEntry(
        name="Carrot",
        bio="Pepper's mischievous orange tabby cat and constant companion.",
        aliases=["the cat"],
    ),
    # ── Chaosah witches (Pepper's godmothers) ──
    _CastEntry(
        name="Thyme",
        bio="The small and wise leader of the Chaosah witches — calculating and sneaky.",
    ),
    _CastEntry(
        name="Cayenne",
        bio="The tall, thin and rigid witch of Chaosah. Spell teacher for Pepper.",
    ),
    _CastEntry(
        name="Cumin",
        bio="A bon-vivant witch of Chaosah. Teacher of potions and potion ingredients for Pepper.",
    ),
    # ── Other young witches (Pepper's peers) ──
    _CastEntry(
        name="Saffron",
        bio="A young witch and frequent rival to Pepper across school competitions.",
    ),
    _CastEntry(
        name="Shichimi",
        bio="A young witch from the Ah school of magic — one of Pepper's friends.",
    ),
    _CastEntry(
        name="Coriander",
        bio="A young witch of Zombiah — granddaughter of Apiaceae and friend in Pepper's circle.",
    ),
    _CastEntry(
        name="Camomile",
        bio="A young witch from Pepper's class at the School of Hippiah Witchcraft.",
    ),
    _CastEntry(
        name="Torreya",
        bio="Pilot of the dragon Arra.",
    ),
    # ── Familiars ──
    _CastEntry(
        name="Truffel",
        bio="A female white angora cat — Saffron's familiar.",
        aliases=["Saffron's cat"],
    ),
    _CastEntry(
        name="Yuzu",
        bio="A two-tailed orange fox (kitsune) that travels beside Shichimi.",
        aliases=["Shichimi's familiar", "kitsune"],
    ),
    _CastEntry(
        name="Mango",
        bio="A black cockerel that is often seen with Coriander.",
        aliases=["Coriander's familiar"],
    ),
    _CastEntry(
        name="Durian",
        bio="A red male betta splendens fish — Spirulina's familiar.",
        aliases=["Spirulina's fish"],
    ),
    _CastEntry(
        name="Squeak",
        bio="A squirrel that lives under Camomile's hat.",
        aliases=["Camomile's familiar"],
    ),
    # ── Magic-school masters ──
    _CastEntry(
        name="Spirulina",
        bio="The mysterious witch-representative of Aquah.",
    ),
    _CastEntry(
        name="Vanilla",
        bio="Master of Magmah, also known as Diva Capsica — passionate, theatrical, dreams of staging the most impressive fire show.",
        aliases=["Diva Capsica"],
    ),
    _CastEntry(
        name="The First Mermaid",
        bio="Master of Aquah — a giant mermaid with a gold trident; possibly mythical.",
    ),
    _CastEntry(
        name="Apiaceae",
        bio="Founder of the Zombiah school and Queen of Qualicity. Coriander's grandmother and Soumbala's creator.",
    ),
    _CastEntry(
        name="Soumbala",
        bio="Master of Zombiah — a robotic creation of Apiaceae's that holds her wisdom.",
    ),
    _CastEntry(
        name="Botanic",
        bio="Former Master of Hippiah, specialised in herbal medicine.",
    ),
    _CastEntry(
        name="Basilic",
        bio="Current Master of Hippiah — apprentice of Botanic, brilliant and a little arrogant.",
    ),
    _CastEntry(
        name="Quassia",
        bio="Teacher of Hippiah.",
    ),
    _CastEntry(
        name="Millet",
        bio="Beloved former teacher of Hippiah.",
    ),
    # ── Adventurers ──
    _CastEntry(
        name="Brasic",
        bio="A human swordsman who hunts treasure alongside Vinya and Frostir.",
    ),
    _CastEntry(
        name="Vinya",
        bio="A ranged adventurer wielding a bow.",
    ),
    _CastEntry(
        name="Frostir",
        bio="An adventurer who travels with Brasic and Vinya.",
    ),
    # ── Other named figures ──
    _CastEntry(
        name="Mayor of Komona",
        bio="The current mayor of Komona City.",
    ),
    _CastEntry(
        name="Prince Acren",
        bio="The uncrowned prince of Acren — orphaned after his parents' death.",
    ),
    _CastEntry(
        name="The Sage",
        bio="The mysterious and wise teacher of Hereva.",
    ),
    _CastEntry(
        name="Fairies",
        bio="Magical winged creatures that inhabit the world of Hereva.",
    ),
]


async def seed_characters(session: AsyncSession) -> tuple[int, int]:
    """Upsert the canonical cast. Returns (inserted, updated) counts."""
    inserted = 0
    updated = 0
    for entry in CANONICAL_CAST:
        existing = await session.scalar(
            select(Character).where(Character.name == entry.name)
        )
        if existing is None:
            session.add(Character(name=entry.name, aliases=list(entry.aliases), bio=entry.bio))
            inserted += 1
        else:
            existing.aliases = list(entry.aliases)
            existing.bio = entry.bio
            updated += 1
    await session.flush()
    return inserted, updated


async def _run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            inserted, updated = await seed_characters(session)
            await session.commit()
            logger.info(
                "Seed complete — inserted=%d updated=%d total=%d",
                inserted,
                updated,
                len(CANONICAL_CAST),
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
