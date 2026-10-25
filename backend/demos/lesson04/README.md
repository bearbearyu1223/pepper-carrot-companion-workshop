# Lesson 4 demos: Reading the Models Line by Line

Every demo in the Lesson 4 video, so you can run it yourself. The files are the ones shown on screen.
In the video they sat directly in `backend/`; here they live in `backend/demos/lesson04/` and run as modules
(`python -m demos.lesson04.<name>`), which is what lets them import `app.*` without extra path code.

All commands run from `backend/`, with the dev stack from Lesson 2 up (`docker compose up -d postgres`).

```bash
cd backend
export FRESH=postgresql://peppercarrot:peppercarrot_dev@localhost:5432/peppercarrot_fresh
```

The demos use two separate databases, so your main `peppercarrot` database is never touched:
`peppercarrot_fresh` (empty; demo I creates it) and `peppercarrot_ep06` (Episode 6's rows; demos E, F, G).
Drop both when you're done:
`docker exec peppercarrot-postgres dropdb -U peppercarrot peppercarrot_fresh` (and the same for `peppercarrot_ep06`).

| Demo | In the video | Files |
|---|---|---|
| H | Alembic starts from a template | (commands only) |
| I | From models to tables | (commands only) |
| J | Watch session.py work | `session_demo.py` |
| A | Watch the types reach the database | `show_ddl.py`, `none_title.py`, `check_summary.py` |
| E | Watch page four in the database | `ep06_seed.sql`, `e_page.sql` |
| F | Watch a chat get written | `f_chat.sql` |
| G | Delete Episode six | `g_delete.sql` |
| B | Why line six matters | (commands only) |
| C | Watch the relationships run | `demo_relationships.py` |
| D | Measure the index | `d_index.sql` |

## H: Alembic starts from a template

In any new, empty folder outside the repo (it creates `alembic.ini` and `alembic/` there):

```bash
export BACKEND=/path/to/pepper-carrot-companion-workshop/backend
mkdir alembic-fresh && cd alembic-fresh
uv run --project $BACKEND alembic list_templates
uv run --project $BACKEND alembic init -t async alembic
grep -n '^sqlalchemy.url' alembic.ini          # a dummy URL
grep -n '^target_metadata' alembic/env.py      # None
```

Compare with the starter's `alembic.ini` and `alembic/env.py`: three edits to `env.py` (import `Base` and the
settings, set the URL from the settings, `target_metadata = Base.metadata`), the URL blanked in `alembic.ini`,
and the ruff post-write hook. Delete the folder afterwards.

## I: From models to tables

```bash
docker exec peppercarrot-postgres createdb -U peppercarrot peppercarrot_fresh
export POSTGRES_DB=peppercarrot_fresh        # Settings reads it before .env
uv run python -c "from app.db.models import Base; print(len(Base.metadata.tables), 'tables:', *Base.metadata.tables)"
uv run alembic current                       # no revision yet
uv run alembic upgrade head
uv run alembic current                       # c04c64861ae8 (head)
psql $FRESH -c '\dt'                         # 10 tables + alembic_version
```

Keep `POSTGRES_DB=peppercarrot_fresh` exported for demos J, A and C.

## J: Watch session.py work

```bash
grep -n 'async_engine_from_config(\|NullPool' alembic/env.py
grep -n 'create_async_engine(\|pool_pre_ping\|async_sessionmaker(\|async def get_session' app/db/session.py
uv run python -m demos.lesson04.session_demo
uv run python -c "from app.db.session import _extract_ssl_connect_args as f; print(f('postgresql+asyncpg://u:p@db.example.com/app?sslmode=require'))"
```

## A: Watch the types reach the database

```bash
uv run python -c "from app.db.models import Episode; print(Episode.__annotations__['title']); print(Episode.__annotations__['plot_summary'])"
uv run python -m demos.lesson04.show_ddl          # the CREATE TABLE SQL SQLAlchemy builds from Episode
uv run python -m demos.lesson04.none_title        # Python accepts title=None; Postgres refuses
uv run mypy demos/lesson04/check_summary.py       # fails on purpose: "str | None"; expected "Sized"
```

## E, F, G: Episode 6, page 4, through every table

These get a database of their own, so the Episode 6 rows (1 episode, 9 pages, 31 characters, 28
`page_characters` rows) never meet the other demos: demo C, for one, creates its own Pepper.

```bash
export EP06=postgresql://peppercarrot:peppercarrot_dev@localhost:5432/peppercarrot_ep06
docker exec peppercarrot-postgres createdb -U peppercarrot peppercarrot_ep06
POSTGRES_DB=peppercarrot_ep06 uv run alembic upgrade head
psql $EP06 -f demos/lesson04/ep06_seed.sql
psql $EP06 -f demos/lesson04/e_page.sql
psql $EP06 -f demos/lesson04/f_chat.sql           # writes a chat inside a transaction, then rolls back
psql $EP06 -f demos/lesson04/g_delete.sql         # deletes Episode 6 inside a transaction, then rolls back
```

The video ran these on the finished app's full database. Your rows for Episode 6 are the same, so E and F match.
G's totals are smaller: the seed has one episode and no chat history, so the delete takes the counts from
9 pages, 28 `page_characters` and 0 sessions to 0, while all 31 characters stay. The cascade is the same.

## B: Why line six matters

```bash
grep -n "__future__" app/db/models.py
uv run python -c "import app.db.models; print('models import fine')"
grep -v "^from __future__" app/db/models.py > no_future_models.py
uv run python -c "import no_future_models"        # NameError: name 'Page' is not defined
rm no_future_models.py
```

## C: Watch the relationships run

```bash
uv run python -m demos.lesson04.demo_relationships  # one transaction, rolled back at the end
```

## D: Measure the index

```bash
psql $FRESH -f demos/lesson04/d_index.sql          # 100,000 messages in a transaction, rolled back
```

Timings vary by machine; the plan shapes (Bitmap Index Scan, Index Scan Backward, Seq Scan) are what to look for.
