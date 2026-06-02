"""Chat message route — a Server-Sent Events stream.

Post 6 returned the whole answer as one JSON body. Post 7 streams it: the
endpoint returns an `EventSourceResponse` that emits `token` events as the model
generates, then a `done` event carrying the message id, the retrieval audit
trail, and the two suggestion chips. The request gains a `mode` field (`page`
or `wiki`) — the user picks it via the UI; the model never decides it.

    curl -N -X POST localhost:8000/api/sessions/$SID/messages \\
      -H 'content-type: application/json' \\
      -d '{"mode":"page","message":"who is on this page?"}'

(`-N` disables curl's buffering so you see tokens arrive live.)
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.ratelimit import SlidingWindowRateLimiter, client_ip
from app.config import get_settings
from app.db.session import get_session
from app.orchestration.chat import ChatOrchestrator, SessionNotFoundError
from app.retrieval.service import Mode

logger = logging.getLogger(__name__)

router = APIRouter()

# Upper bound on a single question. A real question is a sentence or two; this
# is generous for legit use and caps the input-token cost a single abusive
# request can run up (the model's context is otherwise the only ceiling).
# Pydantic rejects anything longer with a 422 before the model is ever called.
_MAX_MESSAGE_CHARS = 2000

# One limiter instance, shared across requests, sized from settings at startup.
_chat_limiter = SlidingWindowRateLimiter(
    max_requests=get_settings().chat_rate_limit_per_minute,
    window_seconds=60.0,
)


async def rate_limit_chat(request: Request) -> None:
    """Per-IP throttle on the cost-bearing chat endpoint.

    Raises HTTP 429 (with ``Retry-After``) past the configured budget. A no-op
    when ``chat_rate_limit_per_minute`` is 0. Tests can disable it per-app via
    ``app.dependency_overrides[rate_limit_chat] = lambda: None``.
    """
    _chat_limiter.check(client_ip(request))


class SendMessageBody(BaseModel):
    mode: Mode
    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_CHARS)
    # Whether a two-page spread is on screen (wide viewport). The client knows
    # its own viewport; the server uses this to describe both visible pages.
    # It does NOT move the spoiler boundary — that stays at the session's
    # current_page.
    spread: bool = False


def get_chat_orchestrator(request: Request) -> ChatOrchestrator:
    """Return the orchestrator built once in `lifespan` and stashed on `app.state`.

    It's `None` when no episode has been ingested (so `pages_v1` doesn't exist);
    chat isn't available then, but the rest of the API still works. Tests
    override this via `app.dependency_overrides[get_chat_orchestrator]`.
    """
    orchestrator = getattr(request.app.state, "chat_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Chat is unavailable — no episode has been ingested yet. Run the "
                "ingestion pipeline (Post 4) and restart the backend."
            ),
        )
    return cast(ChatOrchestrator, orchestrator)


@router.post("/{session_id}/messages", dependencies=[Depends(rate_limit_chat)])
async def send_message(
    session_id: uuid.UUID,
    body: SendMessageBody,
    db: Annotated[AsyncSession, Depends(get_session)],
    orchestrator: Annotated[ChatOrchestrator, Depends(get_chat_orchestrator)],
) -> EventSourceResponse:
    """POST /api/sessions/{id}/messages — stream the answer over SSE."""

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in orchestrator.stream_response(
                db=db,
                session_id=session_id,
                mode=body.mode,
                user_message=body.message,
                spread=body.spread,
            ):
                yield {"event": str(event["event"]), "data": json.dumps(event["data"])}
        except SessionNotFoundError as exc:
            yield {"event": "error", "data": json.dumps({"code": "not_found", "message": str(exc)})}
        except Exception as exc:  # last-resort guard: report the failure as an error event
            logger.exception("chat orchestration crashed for session %s", session_id)
            yield {
                "event": "error",
                "data": json.dumps({"code": "internal_error", "message": str(exc)}),
            }

    # ping=15 sends a comment-only heartbeat every 15s so proxies don't drop the
    # connection during quiet stretches between tokens.
    return EventSourceResponse(event_stream(), ping=15)
