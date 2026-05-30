"""Tests for the chat layer's three bug-prone seams.

`_parse_suggestions` turns the model's named-slot JSON into the SSE chip
array and drops anything that isn't a complete question. `_strip_markdown`
scrubs source markdown out of the text on its way into the prompt — Post 8's
discipline that keeps small models from mirroring `**bold**` and `### headers`
into their replies. The message endpoint frames the orchestrator's events as
Server-Sent Events. All three are tested without a real model — the parsers
are pure, and the endpoint runs against a fake orchestrator injected via
`dependency_overrides`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.api.messages import get_chat_orchestrator
from app.db.session import get_session
from app.main import app
from app.orchestration.chat import _parse_suggestions, _strip_markdown

# ─── _parse_suggestions ───────────────────────────────────────────────────────


def test_parse_named_slots_to_mode_tagged_array() -> None:
    raw = '{"page_chip": "What is on this page", "wiki_chip": "What is Chaosah"}'
    assert _parse_suggestions(raw) == [
        {"mode": "page", "text": "What is on this page"},
        {"mode": "wiki", "text": "What is Chaosah"},
    ]


def test_parse_strips_code_fence() -> None:
    raw = '```json\n{"page_chip": "Who is Pepper", "wiki_chip": "What is Hereva"}\n```'
    assert [c["mode"] for c in _parse_suggestions(raw)] == ["page", "wiki"]


def test_parse_salvages_json_embedded_in_prose() -> None:
    raw = 'Sure! {"page_chip": "Who is Pepper", "wiki_chip": "What is Hereva"} hope that helps'
    assert len(_parse_suggestions(raw)) == 2


def test_parse_drops_a_chip_that_is_not_a_question() -> None:
    # page_chip is a statement, not a question → dropped; wiki_chip survives.
    raw = '{"page_chip": "Carrot is a curious cat", "wiki_chip": "What is Chaosah"}'
    assert _parse_suggestions(raw) == [{"mode": "wiki", "text": "What is Chaosah"}]


def test_parse_drops_a_truncated_chip() -> None:
    # wiki_chip ends on a dangling conjunction → dropped; page_chip survives.
    raw = '{"page_chip": "Who is Pepper", "wiki_chip": "What is Chaosah and"}'
    assert _parse_suggestions(raw) == [{"mode": "page", "text": "Who is Pepper"}]


def test_parse_invalid_or_empty_returns_no_chips() -> None:
    assert _parse_suggestions("definitely not json") == []
    assert _parse_suggestions("") == []


# ─── _strip_markdown (Post 8) ────────────────────────────────────────────────


def test_strip_markdown_removes_inline_markers() -> None:
    assert _strip_markdown("**Pepper** and *Carrot*") == "Pepper and Carrot"
    assert _strip_markdown("__bold__ and _italic_") == "bold and italic"
    assert _strip_markdown("call `embed_batch()` first") == "call embed_batch() first"


def test_strip_markdown_removes_block_markers() -> None:
    src = (
        "## Scene\n"
        "Pepper brews a potion.\n"
        "\n"
        "- the cauldron bubbles\n"
        "- Carrot leans in too close\n"
        "\n"
        "1. she stirs widdershins\n"
        "2. the mix turns silver\n"
        "\n"
        "> a quiet pop\n"
        "---\n"
    )
    out = _strip_markdown(src)
    assert "##" not in out
    assert "- " not in out
    assert "1. " not in out
    assert "> " not in out
    assert "---" not in out
    # The text content survives — only the markers go.
    assert "Pepper brews a potion." in out
    assert "the cauldron bubbles" in out
    assert "she stirs widdershins" in out
    assert "a quiet pop" in out


def test_strip_markdown_leaves_plain_prose_untouched() -> None:
    plain = "Pepper and Carrot tumble through the cottage door."
    assert _strip_markdown(plain) == plain


# ─── SSE message endpoint ──────────────────────────────────────────────────────


class _FakeOrchestrator:
    """Yields a fixed token stream + done event — no model, no DB."""

    async def stream_response(
        self, db: Any, session_id: uuid.UUID, mode: str, user_message: str, spread: bool = False
    ) -> AsyncIterator[dict[str, object]]:
        yield {"event": "token", "data": {"text": "Hello "}}
        yield {"event": "token", "data": {"text": "world"}}
        yield {
            "event": "done",
            "data": {
                "message_id": "m1",
                "retrieved_doc_ids": ["p1"],
                "suggestions": [{"mode": "page", "text": "What happens next"}],
            },
        }


async def test_message_endpoint_frames_events_as_sse() -> None:
    async def fake_session() -> AsyncIterator[object]:
        yield object()  # the fake orchestrator ignores the db handle

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_chat_orchestrator] = lambda: _FakeOrchestrator()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                f"/api/sessions/{uuid.uuid4()}/messages",
                json={"mode": "page", "message": "who is here?"},
            )
        assert r.status_code == 200
        body = r.text
        # Token frames stream the text…
        assert "event: token" in body
        assert "Hello " in body and "world" in body
        # …then a done frame carries the chips.
        assert "event: done" in body
        assert "What happens next" in body
    finally:
        app.dependency_overrides.clear()
