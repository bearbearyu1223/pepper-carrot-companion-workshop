"""Session routes: start a reading session and update the reader's position.

A "session" is the reading-progress record. `chat_sessions.current_page` is the
server-side source of truth for how far the reader has reached — it is what the
retrieval layer's spoiler filter is built from. The browser advances it with
`PATCH` on every page flip; the chat pipeline reads it back, and never trusts a
page number sent alongside a chat message. That separation is the whole point
of Post 6: progress is state the server owns, not a parameter the client (or a
prompt) supplies per question.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.db.session import get_session

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class CreateSessionBody(BaseModel):
    episode_slug: str
    user_email: EmailStr | None = None


class CreateSessionResponse(BaseModel):
    session_id: uuid.UUID
    current_page: int


class UpdateSessionBody(BaseModel):
    current_page: int


@router.post("", response_model=CreateSessionResponse)
async def create_session(
    body: CreateSessionBody,
    db: SessionDep,
) -> CreateSessionResponse:
    """POST /api/sessions — start a reading session for an episode (at page 1)."""
    episode = (
        await db.execute(
            select(models.Episode).where(models.Episode.slug == body.episode_slug)
        )
    ).scalar_one_or_none()
    if episode is None:
        raise HTTPException(
            status_code=404, detail=f"Episode '{body.episode_slug}' not found"
        )

    session = models.ChatSession(
        episode_id=episode.id,
        user_id=body.user_email,
        current_page=1,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return CreateSessionResponse(session_id=session.id, current_page=session.current_page)


@router.patch("/{session_id}")
async def update_session(
    session_id: uuid.UUID,
    body: UpdateSessionBody,
    db: SessionDep,
) -> dict[str, bool]:
    """PATCH /api/sessions/{id} — move the reader's current page.

    Validated against the episode's page count so the stored position is always
    a real page. The frontend calls this on every flip (debounced).
    """
    session = (
        await db.execute(
            select(models.ChatSession).where(models.ChatSession.id == session_id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    page_count = (
        await db.execute(
            select(func.count(models.Page.id)).where(
                models.Page.episode_id == session.episode_id
            )
        )
    ).scalar_one()

    if not 1 <= body.current_page <= page_count:
        raise HTTPException(
            status_code=400,
            detail=f"current_page must be in [1, {page_count}], got {body.current_page}",
        )

    session.current_page = body.current_page
    await db.commit()
    return {"ok": True}
