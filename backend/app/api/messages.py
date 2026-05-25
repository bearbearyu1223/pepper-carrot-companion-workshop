"""Chat message route — ask a question about the current page.

Post 6 returns the whole answer in one JSON response, so the spoiler-safe
pipeline can be exercised end-to-end with `curl`:

    curl -s -X POST localhost:8000/api/sessions/$SID/messages \\
      -H 'content-type: application/json' \\
      -d '{"message": "who is on this page?"}' | jq

Post 7 converts this same endpoint to a Server-Sent Events stream (tokens as
they're generated) and adds the follow-up suggestion chips. The request shape
stays compatible; the response shape changes from JSON to an event stream.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.orchestration.chat import ChatOrchestrator, SessionNotFoundError

router = APIRouter()


class SendMessageBody(BaseModel):
    message: str


class MessageResponse(BaseModel):
    message_id: str
    answer: str
    retrieved_doc_ids: list[str]


def get_chat_orchestrator(request: Request) -> ChatOrchestrator:
    """Return the orchestrator built once in `lifespan` and stashed on `app.state`.

    It's `None` when no episode has been ingested (so `pages_v1` doesn't exist);
    in that case chat isn't available yet, but the rest of the API still works.
    Tests override this via `app.dependency_overrides[get_chat_orchestrator]`.
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


@router.post("/{session_id}/messages", response_model=MessageResponse)
async def send_message(
    session_id: uuid.UUID,
    body: SendMessageBody,
    db: Annotated[AsyncSession, Depends(get_session)],
    orchestrator: Annotated[ChatOrchestrator, Depends(get_chat_orchestrator)],
) -> MessageResponse:
    """POST /api/sessions/{id}/messages — answer a question grounded in the current page."""
    try:
        result = await orchestrator.answer(
            db=db, session_id=session_id, message=body.message
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return MessageResponse(
        message_id=result.message_id,
        answer=result.answer,
        retrieved_doc_ids=result.retrieved_doc_ids,
    )
