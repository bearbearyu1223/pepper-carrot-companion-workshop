import asyncio

from sqlalchemy import func, select

from app.config import get_settings
from app.db import session as db
from app.db.models import Episode


async def main() -> None:
    try:
        await anext(db.get_session())
    except RuntimeError as e:
        print("before init_engine:", e)

    db.init_engine(get_settings().database_url)  # once, at app startup
    print("pool:", db._engine.pool.status())

    sessions = db.get_session()  # what FastAPI does for each request
    s = await anext(sessions)
    print("one request's session:", type(s).__name__)
    print("episodes:", await s.scalar(select(func.count()).select_from(Episode)))
    await sessions.aclose()  # request done: session closed, connection back in the pool
    print("pool:", db._engine.pool.status())

    await db.close_engine()  # at shutdown


asyncio.run(main())
