"""Tests for the world-graph spoiler boundary (Post 9).

The thesis matches Post 6's RAG layer: the spoiler-filter is a structural
property of the SQL query, not a prompt convention. The reader's
(episode_number, page) is in the URL — validated against the episode's
real page count — and the WHERE clause is built from it. No request
field can widen the eligible set.

These tests run against an ephemeral aiosqlite in-memory database with
the same SQLAlchemy models the production Postgres uses, so the
row-value tuple comparison the production query relies on is exercised
end-to-end. The data is hand-crafted so the eligible set is deterministic
for each cursor.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.episodes import get_storage_client
from app.clients.storage import Storage
from app.db.models import (
    Base,
    Episode,
    Page,
    WorldEntity,
    WorldRelationship,
)
from app.db.session import get_session
from app.main import app

# ─── fixtures ─────────────────────────────────────────────────────────────


class _FakeStorage:
    """Stub Storage that composes a deterministic URL for a relative key.

    The world-graph route only ever calls `url_for` on each row, so the
    rest of the Storage protocol can be a no-op here.
    """

    async def url_for(self, key: str) -> str:
        return f"http://test/images/{key}"

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError


@pytest.fixture
async def seeded_session() -> AsyncIterator[AsyncSession]:
    """Build an in-memory SQLite DB, create tables, seed two episodes
    and a handful of entities + edges with hand-crafted debut tuples.

    The graph layout:

      ┌── Entity A — debut (1, 1) — character
      ├── Entity B — debut (1, 5) — character
      ├── Entity C — debut (2, 3) — coven
      └── Entity D — debut (2, 7) — character

      Edge  A→B  kind=friend_of  debut (1, 5)
      Edge  B→C  kind=member_of  debut (2, 3)
      Edge  A→C  kind=member_of  debut (2, 5)   ← edge debuts AFTER both endpoints
      Edge  C→D  kind=rival_of   debut (2, 7)
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        ep1 = Episode(
            slug="ep01",
            title="Episode 1",
            episode_number=1,
            language="en",
            published_at=None,
        )
        ep2 = Episode(
            slug="ep02",
            title="Episode 2",
            episode_number=2,
            language="en",
            published_at=None,
        )
        session.add_all([ep1, ep2])
        await session.flush()

        # 10 pages per episode so the route's page_count clamp has room.
        for ep in (ep1, ep2):
            for n in range(1, 11):
                session.add(
                    Page(
                        episode_id=ep.id,
                        page_number=n,
                        image_url=f"episodes/{ep.slug}/pages/{n:03d}-display.webp",
                    )
                )

        a = WorldEntity(
            slug="a", name="A", kind="character",
            summary="Entity A", image_url="world-graph/images/a-thumb.webp",
            episode_debut=1, page_debut=1, layout_x=0.0, layout_y=0.0,
        )
        b = WorldEntity(
            slug="b", name="B", kind="character",
            summary="Entity B", image_url=None,
            episode_debut=1, page_debut=5, layout_x=100.0, layout_y=0.0,
        )
        c = WorldEntity(
            slug="c", name="C", kind="coven",
            summary="Entity C", image_url=None,
            episode_debut=2, page_debut=3, layout_x=0.0, layout_y=100.0,
        )
        d = WorldEntity(
            slug="d", name="D", kind="character",
            summary="Entity D", image_url=None,
            episode_debut=2, page_debut=7, layout_x=200.0, layout_y=0.0,
        )
        session.add_all([a, b, c, d])
        await session.flush()

        session.add_all([
            WorldRelationship(
                source_id=a.id, target_id=b.id, kind="friend_of",
                episode_debut=1, page_debut=5,
            ),
            WorldRelationship(
                source_id=b.id, target_id=c.id, kind="member_of",
                episode_debut=2, page_debut=3,
            ),
            # Edge debuts AFTER both endpoints — must NOT leak when the
            # reader has both endpoints visible but the edge itself is
            # still in the future.
            WorldRelationship(
                source_id=a.id, target_id=c.id, kind="member_of",
                episode_debut=2, page_debut=5,
            ),
            WorldRelationship(
                source_id=c.id, target_id=d.id, kind="rival_of",
                episode_debut=2, page_debut=7,
            ),
        ])
        await session.commit()

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def override_deps(seeded_session: AsyncSession) -> AsyncIterator[None]:
    """Wire the FastAPI app to the seeded SQLite session + fake storage."""
    async def fake_session() -> AsyncIterator[AsyncSession]:
        yield seeded_session

    def fake_storage() -> Storage:
        return _FakeStorage()  # type: ignore[return-value]

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_storage_client] = fake_storage
    try:
        yield
    finally:
        app.dependency_overrides.clear()


# ─── the boundary itself ──────────────────────────────────────────────────


async def test_only_visible_nodes_are_returned(override_deps: None) -> None:
    """At episode 1 page 4, only entity A (debut (1,1)) is visible."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/world-graph?episode_slug=ep01&page=4")
    assert r.status_code == 200
    body = r.json()
    slugs = {n["slug"] for n in body["nodes"]}
    assert slugs == {"a"}
    # No edges either — every edge has at least one endpoint past the cursor.
    assert body["edges"] == []


async def test_edges_require_both_endpoints_visible(override_deps: None) -> None:
    """At episode 1 page 5, A + B are visible, and A→B (debut (1,5)) shows.

    Neither C nor any edge to C should appear — even though A and B are now
    both visible, no edge to C exists with a debut at or before (1, 5).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/world-graph?episode_slug=ep01&page=5")
    body = r.json()
    assert {n["slug"] for n in body["nodes"]} == {"a", "b"}
    assert len(body["edges"]) == 1
    assert body["edges"][0]["kind"] == "friend_of"


async def test_edge_debut_is_filtered_independently(override_deps: None) -> None:
    """At episode 2 page 4, A + B + C are visible (C debuts (2,3)).

    The A→B edge shows. The B→C edge shows (debut (2,3)). The A→C edge
    must NOT show — it debuts at (2,5), which is past the cursor. This
    is the bug the phase-12 doc warns about: an edge can debut later
    than both of its endpoints.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/world-graph?episode_slug=ep02&page=4")
    body = r.json()
    assert {n["slug"] for n in body["nodes"]} == {"a", "b", "c"}
    edge_kinds = sorted(e["kind"] for e in body["edges"])
    # Only friend_of (1,5) and member_of B→C (2,3) — NOT A→C member_of (2,5).
    assert edge_kinds == ["friend_of", "member_of"]


async def test_later_episode_unlocks_earlier_episode_in_full(
    override_deps: None,
) -> None:
    """At ep2 page 1, every entity from ep1 (any page) is visible.

    This is the lexicographic boundary from Post 6 applied to the graph:
    an earlier episode is fully past, regardless of how far into ep2 the
    reader is. C and D are NOT visible yet (debuts (2,3) and (2,7)).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/world-graph?episode_slug=ep02&page=1")
    body = r.json()
    slugs = {n["slug"] for n in body["nodes"]}
    assert slugs == {"a", "b"}  # both ep1 entities, no ep2 entities yet


async def test_image_url_is_composed_via_storage(override_deps: None) -> None:
    """Relative `pages.image_url` becomes an absolute URL by response time.

    Same convention as the episodes API from Post 5: the DB stores the
    storage key; the route composes the public URL through `Storage`.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/world-graph?episode_slug=ep02&page=10")
    body = r.json()
    node_a = next(n for n in body["nodes"] if n["slug"] == "a")
    assert node_a["image_url"] == "http://test/images/world-graph/images/a-thumb.webp"
    node_b = next(n for n in body["nodes"] if n["slug"] == "b")
    assert node_b["image_url"] is None  # no image on this entity


async def test_unknown_episode_returns_404(override_deps: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/world-graph?episode_slug=does-not-exist&page=1")
    assert r.status_code == 404


async def test_page_past_end_is_clamped(override_deps: None) -> None:
    """A page number past the episode's end clamps to the last page.

    This is what protects against transient ordering glitches in flipbook
    callbacks. The query-string `page=9999` doesn't widen the cursor past
    where the reader actually is.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/api/world-graph?episode_slug=ep02&page=10")
        r2 = await client.get("/api/world-graph?episode_slug=ep02&page=9999")
    # Same cursor → same nodes / edges.
    body1, body2 = r1.json(), r2.json()
    assert {n["id"] for n in body1["nodes"]} == {n["id"] for n in body2["nodes"]}
    assert {e["id"] for e in body1["edges"]} == {e["id"] for e in body2["edges"]}
    # And in this case the cursor (2, 10) makes every entity visible.
    assert {n["slug"] for n in body1["nodes"]} == {"a", "b", "c", "d"}


# ─── focus mode + right_page ────────────────────────────────────────────


async def test_focus_falls_back_to_full_when_no_characters_on_page(
    override_deps: None,
) -> None:
    """The seeded test fixture has no PageCharacter rows, so the focus
    seed comes back empty. The route should silently fall back to the
    spoiler-filtered full subset rather than return an empty panel.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/world-graph?episode_slug=ep02&page=4&mode=focus"
        )
    body = r.json()
    # Same as full mode at the same cursor: A, B, C visible; D not yet.
    assert {n["slug"] for n in body["nodes"]} == {"a", "b", "c"}


async def test_right_page_uses_rightmost_for_spoiler_cursor(
    override_deps: None,
) -> None:
    """`right_page` is the spoiler cursor — the rightmost visible page
    on a two-page spread. `page=4&right_page=6` at episode 2 makes the
    cursor (2, 6), which doesn't unlock anything D-shaped (debut (2,7))
    yet but should be accepted without error.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/world-graph?episode_slug=ep02&page=4&right_page=6"
        )
    assert r.status_code == 200
    body = r.json()
    assert {n["slug"] for n in body["nodes"]} == {"a", "b", "c"}


async def test_right_page_below_left_is_silently_corrected(
    override_deps: None,
) -> None:
    """A transient flipbook ordering glitch can send `right_page < page`.
    The route collapses to single-page mode (right = left) rather than
    400-ing the response. Cursor (2, 5) now lets A→C member_of (debut
    (2, 5)) appear.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/world-graph?episode_slug=ep02&page=5&right_page=2"
        )
    assert r.status_code == 200
    body = r.json()
    assert {n["slug"] for n in body["nodes"]} == {"a", "b", "c"}
    # At (2, 5): friend_of (1,5), B→C member_of (2,3), AND A→C member_of (2,5).
    edge_kinds = sorted(e["kind"] for e in body["edges"])
    assert edge_kinds == ["friend_of", "member_of", "member_of"]


# Silence pytest's "unused fixture" warning when seeded_session is consumed
# transitively via override_deps; the import is the dependency hint.
_ = uuid
