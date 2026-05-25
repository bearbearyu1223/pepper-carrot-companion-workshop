"""Chat orchestration — the runtime pipeline that turns a question into an answer.

The flow, in one method (`answer`):

  1. Load session context: which episode, which page the reader is on.
  2. Persist the user's message (so there's a record even if generation fails).
  3. Retrieve — spoiler-filtered page chunks, scoped by the session's position.
  4. Fetch the full text of those chunks from Postgres (the source of truth).
  5. Assemble the prompt: current-page notes + earlier-page reference context.
  6. Call the chat model.
  7. Persist the assistant message plus the retrieval audit trail.

Post 6 answers in a single non-streaming call so the whole pipeline is
exercisable with `curl`. Post 7 swaps step 6 for a token stream over SSE, adds
prior-turn history to the prompt, and generates the follow-up suggestion chips.

See docs/chat-orchestration.md (full project) for the streaming design.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients.chat import ChatClient, ContentBlockText, Message
from app.core.prompts import render_system_prompt
from app.db import models
from app.retrieval.service import RetrievalService, RetrievedChunk

logger = logging.getLogger(__name__)

# Page mode is the only mode in Post 6; recorded on each message so the row is
# already shaped for the wiki mode that arrives in Post 7.
_PAGE_MODE = "page"

# The answer is capped at a few sentences by the prompt, but give the model
# enough room that a slightly longer reply isn't truncated mid-thought.
_ANSWER_MAX_TOKENS = 512


class SessionNotFoundError(RuntimeError):
    """The session doesn't exist, or its current page isn't in the episode."""


@dataclass(frozen=True)
class AnswerResult:
    """What `answer()` returns: the saved message id, the text, and the audit trail."""

    message_id: str
    answer: str
    retrieved_doc_ids: list[str]


class ChatOrchestrator:
    """Assembles retrieval + prompt + model call into a grounded answer.

    Built once at startup (it holds the `RetrievalService`, which holds a Chroma
    client and an embedding model) and shared across requests via `app.state`.
    """

    def __init__(self, chat_client: ChatClient, retrieval: RetrievalService) -> None:
        self._chat = chat_client
        self._retrieval = retrieval

    async def answer(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        message: str,
    ) -> AnswerResult:
        started_at = time.monotonic()

        # 1. Resolve session context (episode + the page the reader is on).
        session, episode, page = await self._load_context(db, session_id)

        # 2. Persist the user message immediately.
        db.add(
            models.ChatMessage(
                session_id=session.id,
                role="user",
                mode=_PAGE_MODE,
                content=message,
            )
        )
        await db.commit()

        # 3. Retrieve. The boundary comes from the *session row*, not `message`.
        chunks = await self._retrieval.retrieve(
            message,
            current_episode_number=episode.episode_number,
            current_page_number=session.current_page,
        )

        # 4. Fetch the full text for those chunks (Postgres is source of truth).
        retrieved_text = await self._fetch_page_text(db, chunks)

        # 5. Build the prompt.
        system_prompt = render_system_prompt(
            episode_number=episode.episode_number,
            episode_title=episode.title,
            current_page=session.current_page,
        )
        user_turn = self._assemble_user_turn(episode, page, message, retrieved_text)

        # 6. Call the model (non-streaming in Post 6).
        answer_text = await self._chat.complete(
            system=system_prompt,
            messages=[Message(role="user", content=[ContentBlockText(text=user_turn)])],
            max_tokens=_ANSWER_MAX_TOKENS,
        )

        # 7. Persist the assistant message + retrieval audit trail.
        retrieved_ids = [c.chroma_id for c in chunks]
        assistant_msg = models.ChatMessage(
            session_id=session.id,
            role="assistant",
            mode=_PAGE_MODE,
            content=answer_text,
            retrieved_doc_ids=retrieved_ids,
            latency_ms=int((time.monotonic() - started_at) * 1000),
        )
        db.add(assistant_msg)
        await db.commit()
        await db.refresh(assistant_msg)

        return AnswerResult(
            message_id=str(assistant_msg.id),
            answer=answer_text,
            retrieved_doc_ids=retrieved_ids,
        )

    # ─── private ──────────────────────────────────────────────────────────────

    async def _load_context(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> tuple[models.ChatSession, models.Episode, models.Page]:
        """Fetch the session, its episode, and the page the reader is on.

        Post 6 grounds answers in the single current page. (The full project
        loads a 2-page spread on wide viewports; that's a presentation detail
        the workshop skips to keep the pipeline legible.) `page.characters` is
        eager-loaded so the prompt can name who's on the page without a second
        round-trip.
        """
        stmt = (
            select(models.ChatSession, models.Episode, models.Page)
            .join(models.Episode, models.ChatSession.episode_id == models.Episode.id)
            .join(
                models.Page,
                (models.Page.episode_id == models.Episode.id)
                & (models.Page.page_number == models.ChatSession.current_page),
            )
            .where(models.ChatSession.id == session_id)
            .options(selectinload(models.Page.characters))
        )
        row = (await db.execute(stmt)).one_or_none()
        if row is None:
            raise SessionNotFoundError(
                f"Session {session_id} not found, or its current page has no row "
                "in the linked episode."
            )
        session, episode, page = row
        return session, episode, page

    async def _fetch_page_text(
        self,
        db: AsyncSession,
        chunks: list[RetrievedChunk],
    ) -> list[tuple[RetrievedChunk, str]]:
        """Look up each chunk's canonical text from Postgres by `source_id`.

        One `IN` query for every page chunk; order is preserved by re-indexing
        through the original `chunks` list. A chunk whose text we can't resolve
        maps to "" and is dropped during prompt assembly.
        """
        if not chunks:
            return []

        page_ids: list[uuid.UUID] = []
        for chunk in chunks:
            if chunk.source_table != "pages":
                continue
            try:
                page_ids.append(uuid.UUID(chunk.source_id))
            except ValueError:
                continue

        text_by_id: dict[str, str] = {}
        if page_ids:
            stmt = (
                select(models.Page)
                .where(models.Page.id.in_(page_ids))
                .options(selectinload(models.Page.characters))
            )
            for page in (await db.execute(stmt)).scalars():
                description = page.visual_description or ""
                if page.characters:
                    names = ", ".join(sorted(c.name for c in page.characters))
                    description = f"Featuring {names}. {description}"
                text_by_id[str(page.id)] = description

        return [(chunk, text_by_id.get(chunk.source_id, "")) for chunk in chunks]

    @staticmethod
    def _assemble_user_turn(
        episode: models.Episode,
        page: models.Page,
        message: str,
        retrieved_text: list[tuple[RetrievedChunk, str]],
    ) -> str:
        """Build the single user-turn text block: page notes + references + question.

        Everything the model is allowed to ground on is in this one message,
        under labeled sections. The "Reference context" section only ever holds
        pages the reader has already passed — the retrieval layer guaranteed
        that upstream.
        """
        parts: list[str] = []

        if episode.plot_summary:
            parts.append("=== About this episode ===")
            parts.append(episode.plot_summary)
            parts.append("")

        parts.append(f"=== Current page (page {page.page_number}) ===")
        if page.characters:
            names = ", ".join(sorted(c.name for c in page.characters))
            parts.append(f"Characters on this page: {names}")
        parts.append(page.visual_description or "(no description available for this page)")
        if page.ocr_text:
            parts.append("")
            parts.append("Dialogue on this page:")
            parts.append(page.ocr_text)
        if page.mood_tags:
            parts.append(f"Mood: {', '.join(page.mood_tags)}")

        references = [(chunk, text) for chunk, text in retrieved_text if text]
        if references:
            parts.append("")
            parts.append("=== Reference context (earlier pages you've already read) ===")
            for chunk, text in references:
                ep = chunk.metadata.get("episode_number")
                pg = chunk.metadata.get("page_number")
                parts.append(f"From page {pg} of episode {ep}: {text}")

        parts.append("")
        parts.append("=== User question ===")
        parts.append(message)

        return "\n".join(parts)
