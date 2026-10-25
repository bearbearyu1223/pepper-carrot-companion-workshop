import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.db.models import Episode


async def main() -> None:
    ep = Episode(slug="ep99", title=None, episode_number=99)  # Python allows it
    print("Python accepted title =", ep.title)
    engine = create_async_engine(get_settings().database_url)
    async with AsyncSession(engine) as s:
        s.add(ep)
        try:
            await s.flush()
        except Exception as e:
            print(type(e.orig).__name__, "->", str(e.orig).splitlines()[0])
            await s.rollback()
    await engine.dispose()


asyncio.run(main())
