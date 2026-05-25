"""Smoke tests for the episodes API.

The load-bearing thing to verify is that `pages.image_url` (a relative
storage key in the database) becomes an **absolute URL** by the time it
reaches the JSON response — i.e. that `Storage.url_for()` is wired into the
route and not bypassed. Both tests inject a fake DB session and a stub
storage so the test is hermetic — no Postgres or filesystem required.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.episodes import get_storage_client
from app.db.models import Character, Episode, Page
from app.db.session import get_session
from app.main import app


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Minimal async-session stand-in that returns prebuilt rows.

    The episodes router issues two distinct SELECTs (the list query joins
    a page-count subquery; the detail query selects an Episode). We branch
    on the first `FROM` clause to pick the right canned response.
    """

    def __init__(self, *, list_rows: list[Any], detail_row: Any) -> None:
        self._list_rows = list_rows
        self._detail_row = detail_row

    async def execute(self, stmt: Any) -> _FakeResult:
        # The list query is "SELECT Episode, page_count FROM episodes LEFT OUTER JOIN ..."
        # The detail query is "SELECT Episode FROM episodes WHERE slug = ..."
        compiled = str(stmt).lower()
        if "left outer join" in compiled:
            return _FakeResult(self._list_rows)
        return _FakeResult([self._detail_row] if self._detail_row else [])


def _make_episode_with_pages() -> Episode:
    """Build a detached Episode ORM object with two pages and one character."""
    episode = Episode(
        id=uuid.uuid4(),
        slug="ep01-potion-of-flight",
        title="Potion of Flight",
        episode_number=1,
        language="en",
        cover_image_url="episodes/ep01-potion-of-flight/cover.webp",
        plot_summary="Pepper brews a potion of flight, Carrot leaps in.",
        credits_url=None,
        published_at=datetime(2014, 1, 1, tzinfo=UTC),
        ingested_at=datetime.now(tz=UTC),
    )
    pepper = Character(id=uuid.uuid4(), name="Pepper", aliases=[], image_url=None)
    pages: list[Page] = []
    for n in (1, 2):
        page = Page(
            id=uuid.uuid4(),
            episode_id=episode.id,
            page_number=n,
            image_url=f"episodes/ep01-potion-of-flight/pages/{n:03d}-display.webp",
            thumbnail_url=f"episodes/ep01-potion-of-flight/pages/{n:03d}-thumbnail.webp",
            original_url=None,
            ocr_text=None,
            visual_description=None,
            mood_tags=[],
            image_metadata={"width": 1600, "height": 1131, "dominant_color": "#e7d3a8"},
        )
        page.characters = [pepper]
        pages.append(page)
    episode.pages = pages
    return episode


@pytest.fixture
def fake_episode() -> Episode:
    return _make_episode_with_pages()


@pytest.fixture
def client(fake_episode: Episode) -> AsyncClient:
    """An httpx client wired to the FastAPI app with stub session + storage."""

    async def override_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(
            list_rows=[(fake_episode, len(fake_episode.pages))],
            detail_row=fake_episode,
        )

    storage = AsyncMock()
    # url_for is the only Storage method the routes touch. Stub it to a
    # predictable prefix so we can assert against the exact returned URL.
    storage.url_for.side_effect = lambda key: f"http://test/images/{key}"

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_storage_client] = lambda: storage

    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_list_returns_one_episode_with_resolved_cover(
    client: AsyncClient, fake_episode: Episode
) -> None:
    async with client as c:
        r = await c.get("/api/episodes")
    assert r.status_code == 200
    body = r.json()
    assert len(body["episodes"]) == 1
    item = body["episodes"][0]
    assert item["slug"] == fake_episode.slug
    assert item["page_count"] == 2
    # Cover URL was a relative key in the DB; the API must have run it
    # through storage.url_for() before returning.
    assert fake_episode.cover_image_url is not None  # for the type-checker
    assert item["cover_image_url"] == "http://test/images/" + fake_episode.cover_image_url
    app.dependency_overrides.clear()


async def test_detail_returns_absolute_image_urls_for_every_page(
    client: AsyncClient, fake_episode: Episode
) -> None:
    async with client as c:
        r = await c.get("/api/episodes/ep01-potion-of-flight")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "ep01-potion-of-flight"
    assert len(body["pages"]) == 2
    for page in body["pages"]:
        # The load-bearing assertion: relative key turned into an absolute URL.
        assert page["image_url"].startswith("http://test/images/")
        assert page["thumbnail_url"].startswith("http://test/images/")
    app.dependency_overrides.clear()


async def test_detail_returns_404_for_unknown_slug(client: AsyncClient) -> None:
    # Re-override session to return no episode for the detail query.
    async def empty_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(list_rows=[], detail_row=None)

    app.dependency_overrides[get_session] = empty_session

    async with client as c:
        r = await c.get("/api/episodes/does-not-exist")
    assert r.status_code == 404
    app.dependency_overrides.clear()
