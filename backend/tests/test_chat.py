"""Tests for the chat layer's two bug-prone seams: the suggestion-chip parser
and the SSE event framing.

`_parse_suggestions` turns the model's named-slot JSON into the SSE chip array
and drops anything that isn't a complete question. The message endpoint frames
the orchestrator's events as Server-Sent Events. Both are tested without a real
model — the parser is pure, and the endpoint runs against a fake orchestrator
injected via `dependency_overrides`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.api.messages import get_chat_orchestrator
from app.db.session import get_session
from app.main import app
from app.orchestration.chat import _parse_suggestions


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


# ─── SSE message endpoint ──────────────────────────────────────────────────────


class _FakeOrchestrator:
    """Yields a fixed token stream + done event — no model, no DB."""

    async def stream_response(
        self, db: Any, session_id: uuid.UUID, mode: str, user_message: str
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
