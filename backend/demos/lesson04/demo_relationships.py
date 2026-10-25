"""Watch the relationship() settings in models.py work. One transaction, rolled back at the end."""

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Character, Episode, Page, PageCharacter


def count(s: Session, model: type) -> int:
    return s.scalar(select(func.count()).select_from(model)) or 0


def demo(s: Session) -> None:
    ep = Episode(slug="ep01-potion-of-flight", title="Episode 1: The Potion of Flight",
                 episode_number=1)
    for n in (3, 1, 2):
        ep.pages.append(Page(page_number=n, image_url=f"episodes/ep01/pages/{n:03d}.webp"))
    page3 = ep.pages[0]
    print("back_populates  page3.episode is ep:", page3.episode is ep)

    s.add(ep)
    s.flush()
    s.expire(ep)
    print("order_by        ep.pages:", [p.page_number for p in ep.pages])

    pepper = Character(name="Pepper")
    page3.characters.append(pepper)
    s.flush()
    print("secondary       page_characters rows:", count(s, PageCharacter),
          "| pepper.pages:", [p.page_number for p in pepper.pages])

    s.delete(ep)
    s.flush()
    print("cascade         pages:", count(s, Page), "| page_characters:",
          count(s, PageCharacter), "| characters:", count(s, Character))


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with AsyncSession(engine) as session:
        await session.run_sync(demo)
        await session.rollback()
    await engine.dispose()


asyncio.run(main())
