"""Chat orchestration — the streaming runtime pipeline.

`stream_response()` runs the whole flow and yields Server-Sent-Events-shaped
dicts as it goes:

  1. Load session context (episode + current page).
  2. Persist the user message (so a record survives a mid-stream failure).
  3. Retrieve — page mode is spoiler-filtered; wiki mode isn't.
  4. Fetch the retrieved chunks' canonical text from Postgres.
  5. Build the per-mode prompt (+ a few prior turns of history).
  6. Stream tokens from the chat model, yielding a `token` event per token.
  7. Persist the assistant message + the retrieval audit trail.
  8. Generate two follow-up suggestion chips (a second, schema-constrained call).
  9. Yield a `done` event carrying the message id, retrieved ids, and chips.

The events are framed as SSE by the route (`api/messages.py`); this module only
decides their shape. Post 6 answered in one non-streaming call; Post 7 turns
that into the token stream above and adds the chips. Post 8 adds the
`_strip_markdown` helper that scrubs `**bold**`, `### headers`, `- bullets`
and friends out of every piece of text on its way into the prompt — small
chat models mirror whatever formatting they see in context, so removing the
markers at the source is what keeps replies as plain conversational prose.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients.chat import ChatClient, ContentBlockText, Message
from app.core.prompts import SUGGESTIONS_SYSTEM, render_system_prompt
from app.db import models
from app.retrieval.service import Mode, RetrievalService, RetrievedChunk

logger = logging.getLogger(__name__)

# How many prior turns to replay into the prompt (user+assistant counts as 2).
HISTORY_TURNS = 5

# The answer is capped at a few sentences by the prompt; give it enough room
# that a slightly longer reply isn't truncated mid-thought.
_ANSWER_MAX_TOKENS = 512

# The suggestion call is tiny and non-streaming.
SUGGESTION_MAX_TOKENS = 200
_SUGGESTION_TEXT_MAX_CHARS = 200

# JSON schema the chat client enforces during sampling (Ollama's `format`).
# Two **named slots** — not an array of `{mode, text}` — so the model
# structurally cannot return two chips of the same mode. The orchestrator
# converts this object back into the SSE array `[{mode, text}, {mode, text}]`.
_SUGGESTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page_chip": {
            "type": "string",
            "minLength": 4,
            "maxLength": _SUGGESTION_TEXT_MAX_CHARS,
            "description": "A complete follow-up question about the current comic page.",
        },
        "wiki_chip": {
            "type": "string",
            "minLength": 4,
            "maxLength": _SUGGESTION_TEXT_MAX_CHARS,
            "description": "A complete follow-up question about the Pepper&Carrot universe.",
        },
    },
    "required": ["page_chip", "wiki_chip"],
    "additionalProperties": False,
}


# Markdown-stripping. The page descriptions written by the `ingest-from-images`
# skill and the wiki seed articles are both markdown-heavy at the source — they
# carry `**bold**` for proper nouns, `### headers`, `- bullets`, and so on.
# Small chat models mirror whatever formatting they see in context, so an essay
# question reliably comes back as a four-section essay. We strip the formatting
# characters before the model sees them; the text content survives, only the
# markers disappear. The frontend separately renders any markdown the model
# *does* emit as a safety net (Post 8), so the discipline is in both places.
_MARKDOWN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\*\*([^*\n]+?)\*\*"), r"\1"),                # **bold**
    (re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)"), r"\1"),       # *italic*
    (re.compile(r"__([^_\n]+?)__"), r"\1"),                    # __bold__
    (re.compile(r"(?<!_)_([^_\n]+?)_(?!_)"), r"\1"),           # _italic_
    (re.compile(r"`([^`\n]+?)`"), r"\1"),                      # `code`
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),             # # headers
    (re.compile(r"^\s*[-*•]\s+", re.MULTILINE), ""),           # - bullets
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""),           # 1. numbered
    (re.compile(r"^\s*>\s?", re.MULTILINE), ""),               # > blockquotes
    (re.compile(r"^\s*-{3,}\s*$", re.MULTILINE), ""),          # --- rules
    (re.compile(r"\n{3,}"), "\n\n"),                           # collapse blank runs
)


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting so the chat model sees plain prose.

    Applied to every piece of text that ends up in the user-turn prompt:
    `episode.plot_summary`, `page.visual_description`, `page.ocr_text`, each
    retrieved page's description, and each retrieved wiki article's content.
    """
    for pattern, replacement in _MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


class SessionNotFoundError(RuntimeError):
    """The session doesn't exist, or its current page isn't in the episode."""


class ChatOrchestrator:
    """Assembles retrieval + prompt + a streamed model call into an answer.

    Built once at startup (it holds the `RetrievalService`, which holds a Chroma
    client and an embedding model) and shared across requests via `app.state`.
    """

    def __init__(self, chat_client: ChatClient, retrieval: RetrievalService) -> None:
        self._chat = chat_client
        self._retrieval = retrieval

    async def stream_response(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        mode: Mode,
        user_message: str,
        spread: bool = False,
    ) -> AsyncIterator[dict[str, object]]:
        """Run the pipeline, yielding SSE-shaped events.

        `spread` is the client's report of whether a two-page spread is on
        screen (wide viewport). When True, page mode describes both visible
        pages — see `_load_context`. It does not affect the spoiler boundary.

        Events:
          {"event": "token", "data": {"text": "..."}}
          {"event": "done",  "data": {"message_id", "retrieved_doc_ids", "suggestions"}}
          {"event": "error", "data": {"code", "message"}}
        """
        started_at = time.monotonic()

        # 1. Resolve session context — the visible page(s): one, or both on a spread.
        session, episode, pages = await self._load_context(db, session_id, spread=spread)

        # 2. Persist the user message immediately.
        db.add(
            models.ChatMessage(
                session_id=session.id, role="user", mode=mode, content=user_message
            )
        )
        await db.commit()

        # 3. Retrieve. Page mode is spoiler-filtered from the session row; wiki
        #    mode is unfiltered. The boundary never comes from `user_message`.
        chunks = await self._retrieval.retrieve(
            mode,
            user_message,
            current_episode_number=episode.episode_number,
            current_page_number=session.current_page,
        )

        # 4. Fetch the chunks' full text from Postgres (the source of truth).
        retrieved_text = await self._fetch_chunk_text(db, chunks)

        # 5. Build the prompt (system + history + the labeled user turn).
        system_prompt = render_system_prompt(
            mode,
            episode_number=episode.episode_number,
            episode_title=episode.title,
            current_page=session.current_page,
        )
        messages = await self._assemble_messages(
            db, session, episode, pages, mode, user_message, retrieved_text
        )

        # 6. Stream tokens.
        accumulated = ""
        try:
            async for token in self._chat.stream(
                system=system_prompt, messages=messages, max_tokens=_ANSWER_MAX_TOKENS
            ):
                accumulated += token
                yield {"event": "token", "data": {"text": token}}
        except Exception as exc:  # surface any model/transport failure as an error event
            logger.exception("token streaming failed for session %s", session_id)
            yield {"event": "error", "data": {"code": "generation_failed", "message": str(exc)}}
            return

        # 7. Persist the assistant message + retrieval audit trail.
        retrieved_ids = [c.chroma_id for c in chunks]
        assistant_msg = models.ChatMessage(
            session_id=session.id,
            role="assistant",
            mode=mode,
            content=accumulated,
            retrieved_doc_ids=retrieved_ids,
            latency_ms=int((time.monotonic() - started_at) * 1000),
        )
        db.add(assistant_msg)
        await db.commit()
        await db.refresh(assistant_msg)

        # 8. Suggestions — a second, schema-constrained call. Non-fatal.
        suggestions = await self._generate_suggestions(user_message, accumulated)

        # 9. Done.
        yield {
            "event": "done",
            "data": {
                "message_id": str(assistant_msg.id),
                "retrieved_doc_ids": retrieved_ids,
                "suggestions": suggestions,
            },
        }

    # ─── context loading ───────────────────────────────────────────────────────

    async def _load_context(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        *,
        spread: bool,
    ) -> tuple[models.ChatSession, models.Episode, list[models.Page]]:
        """Fetch the session, its episode, and the page(s) the reader can see.

        `chat_sessions.current_page` is the leftmost visible page. On a wide
        viewport the flipbook shows a two-page spread, so the client passes
        `spread=True` and we also load `current_page + 1` when it exists — the
        chat should reflect everything on screen, not just the left page. In
        portrait (single page) `spread` is False and only the current page loads.

        This does not widen the spoiler boundary: retrieval is still gated at
        `current_page` (see `RetrievalService`). The right-hand page is fed
        directly because the reader is *looking at it* — a page on screen can't
        be a spoiler.
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
        session, episode, left_page = row
        pages = [left_page]

        if spread:
            right_stmt = (
                select(models.Page)
                .where(
                    models.Page.episode_id == episode.id,
                    models.Page.page_number == session.current_page + 1,
                )
                .options(selectinload(models.Page.characters))
            )
            right_page = (await db.execute(right_stmt)).scalar_one_or_none()
            if right_page is not None:
                pages.append(right_page)

        return session, episode, pages

    async def _fetch_chunk_text(
        self,
        db: AsyncSession,
        chunks: list[RetrievedChunk],
    ) -> list[tuple[RetrievedChunk, str]]:
        """Look up each chunk's canonical text from Postgres by source table + id.

        One `IN` query per source table. Order is preserved by re-indexing
        through the original `chunks` list.
        """
        if not chunks:
            return []

        ids_by_table: dict[str, list[uuid.UUID]] = {}
        for chunk in chunks:
            try:
                ids_by_table.setdefault(chunk.source_table, []).append(
                    uuid.UUID(chunk.source_id)
                )
            except ValueError:
                continue

        text_lookup: dict[tuple[str, str], str] = {}

        if "pages" in ids_by_table:
            page_stmt = (
                select(models.Page)
                .where(models.Page.id.in_(ids_by_table["pages"]))
                .options(selectinload(models.Page.characters))
            )
            for page in (await db.execute(page_stmt)).scalars():
                description = _strip_markdown(page.visual_description or "")
                if page.characters:
                    names = ", ".join(sorted(c.name for c in page.characters))
                    description = f"Featuring {names}. {description}"
                text_lookup[("pages", str(page.id))] = description

        if "wiki" in ids_by_table:
            wiki_stmt = select(models.WikiArticle).where(
                models.WikiArticle.id.in_(ids_by_table["wiki"])
            )
            for article in (await db.execute(wiki_stmt)).scalars():
                # title + body, so attribution and content are both available.
                # Wiki seed articles are markdown-heavy at source — strip the
                # formatting so the model doesn't mirror it in the answer.
                text_lookup[("wiki", str(article.id))] = (
                    f"{article.title}\n\n{_strip_markdown(article.content)}"
                )

        return [
            (chunk, text_lookup.get((chunk.source_table, chunk.source_id), ""))
            for chunk in chunks
        ]

    # ─── prompt assembly ─────────────────────────────────────────────────────────

    async def _assemble_messages(
        self,
        db: AsyncSession,
        session: models.ChatSession,
        episode: models.Episode,
        pages: list[models.Page],
        mode: Mode,
        user_message: str,
        retrieved_text: list[tuple[RetrievedChunk, str]],
    ) -> list[Message]:
        """Build the message list: prior turns, then the labeled current turn."""
        history = await self._load_history(db, session.id)

        parts: list[str] = []
        if mode == "page":
            self._render_page_block(parts, episode, pages)
            references = [(c, t) for c, t in retrieved_text if t]
            if references:
                parts.append("")
                parts.append("=== Reference context (earlier pages you've already read) ===")
                for chunk, text in references:
                    ep = chunk.metadata.get("episode_number")
                    pg = chunk.metadata.get("page_number")
                    parts.append(f"From page {pg} of episode {ep}: {text}")
        else:  # wiki
            articles = [(c, t) for c, t in retrieved_text if t]
            parts.append("=== Wiki context ===")
            if articles:
                for _chunk, text in articles:
                    title, _, body = text.partition("\n\n")
                    parts.append(f"From the wiki article '{title}': {body or text}")
            else:
                parts.append("(no wiki articles matched this question)")

        parts.append("")
        parts.append("=== User question ===")
        parts.append(user_message)

        final_turn = Message(role="user", content=[ContentBlockText(text="\n".join(parts))])
        return [*history, final_turn]

    @staticmethod
    def _render_page_block(
        parts: list[str], episode: models.Episode, pages: list[models.Page]
    ) -> None:
        """Describe the visible page(s). On a spread, both are labeled so the
        model can attribute facts to the right page."""
        if episode.plot_summary:
            parts.append("=== About this episode ===")
            parts.append(_strip_markdown(episode.plot_summary))
            parts.append("")

        if len(pages) == 2:
            parts.append(
                f"=== Current spread (pages {pages[0].page_number} and "
                f"{pages[1].page_number}, both visible to the reader) ==="
            )
        else:
            parts.append(f"=== Current page (page {pages[0].page_number}) ===")

        for page in pages:
            if len(pages) == 2:
                parts.append("")
                parts.append(f"-- Page {page.page_number} --")
            if page.characters:
                names = ", ".join(sorted(c.name for c in page.characters))
                parts.append(f"Characters on this page: {names}")
            parts.append(
                _strip_markdown(page.visual_description)
                if page.visual_description
                else "(no description available for this page)"
            )
            if page.ocr_text:
                parts.append("")
                parts.append("Dialogue on this page:")
                parts.append(_strip_markdown(page.ocr_text))
            if page.mood_tags:
                parts.append(f"Mood: {', '.join(page.mood_tags)}")

    async def _load_history(
        self, db: AsyncSession, session_id: uuid.UUID
    ) -> list[Message]:
        """Replay the last HISTORY_TURNS turns, oldest first.

        The just-saved user message is included by the query (it ran after the
        commit in step 2), so we trim it off the end — it's the message we're
        responding to, added separately as the final turn.
        """
        stmt = (
            select(models.ChatMessage)
            .where(models.ChatMessage.session_id == session_id)
            .order_by(models.ChatMessage.created_at.desc())
            .limit(HISTORY_TURNS * 2 + 1)
        )
        rows = list(reversed(list((await db.execute(stmt)).scalars())))
        if rows and rows[-1].role == "user":
            rows = rows[:-1]
        history: list[Message] = []
        for row in rows:
            role: Literal["user", "assistant"] = (
                "assistant" if row.role == "assistant" else "user"
            )
            history.append(Message(role=role, content=[ContentBlockText(text=row.content)]))
        return history

    # ─── suggestion chips ────────────────────────────────────────────────────────

    async def _generate_suggestions(
        self, user_message: str, assistant_response: str
    ) -> list[dict[str, str]]:
        """Ask the model for two follow-up chips — one page, one wiki.

        Schema-constrained (`_SUGGESTIONS_SCHEMA`) and bounded. Any failure
        returns `[]`: chips are an enhancement, not a requirement, so the
        caller proceeds without them.
        """
        if not assistant_response.strip():
            return []
        prompt_user = (
            "Here is an example for a DIFFERENT conversation:\n"
            "  USER ASKED: who is the witch on the broom?\n"
            "  ASSISTANT ANSWERED: That's Coriander, a young witch known for her "
            "broom-flying.\n"
            '  CORRECT OUTPUT: {"page_chip": "What is Coriander reaching for on this page", '
            '"wiki_chip": "What witch school does Coriander belong to"}\n\n'
            "Now do the same for THIS conversation:\n"
            f"  USER ASKED: {user_message}\n"
            f"  ASSISTANT ANSWERED: {assistant_response}\n\n"
            "OUTPUT (JSON object only, two complete question chips):"
        )
        try:
            raw = await self._chat.complete(
                system=SUGGESTIONS_SYSTEM,
                messages=[Message(role="user", content=[ContentBlockText(text=prompt_user)])],
                max_tokens=SUGGESTION_MAX_TOKENS,
                json_format=_SUGGESTIONS_SCHEMA,
            )
        except Exception:
            logger.exception("suggestion generation failed; returning none")
            return []
        chips = _parse_suggestions(raw)
        if not chips:
            logger.warning("suggestion parser returned 0 chips from raw=%r", raw[:200])
        return chips


# ─── suggestion parsing (module-level, easy to unit-test) ──────────────────────

# A chip must start with one of these to read as an actual question. Small models
# sometimes emit a description shaped like a sentence ("Carrot is Pepper's cat");
# those make terrible chips, so we drop them.
_QUESTION_STEMS: tuple[str, ...] = (
    "what", "who", "why", "how", "where", "when", "which", "whose",
    "is", "are", "does", "do", "did", "can", "could", "would", "will", "should",
    "tell me", "show me", "explain", "describe",
)

# A chip ending in one of these was cut off mid-thought.
_TRUNCATION_TRAILERS: tuple[str, ...] = (",", "-", "—", ":", ";", '"', "'")


def _looks_like_question(text: str) -> bool:
    head = text.strip().lower()
    return any(head.startswith(stem) for stem in _QUESTION_STEMS)


def _looks_complete(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if cleaned[-1] in _TRUNCATION_TRAILERS:
        return False
    last_word = cleaned.split()[-1].lower().rstrip(".?!")
    return last_word not in {"and", "or", "but", "with", "to", "of", "for", "the", "a"}


def _parse_suggestions(raw: str) -> list[dict[str, str]]:
    """Parse the named-slot chip JSON into the SSE array `[{mode, text}, …]`.

    Schema enforcement happens at sampling time, but we still parse defensively:
    strip code fences, salvage JSON embedded in prose, then drop any chip that
    isn't a complete question. Anything unsalvageable yields `[]`.
    """
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        logger.warning("suggestion parse: no JSON object in %r", raw[:200])
        return []
    try:
        parsed: Any = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("suggestion parse: invalid JSON in %r", raw[:200])
        return []
    if not isinstance(parsed, dict):
        return []

    candidates: list[dict[str, str]] = []
    for mode_name, schema_key in (("page", "page_chip"), ("wiki", "wiki_chip")):
        value = parsed.get(schema_key)
        if isinstance(value, str) and value.strip():
            candidates.append({"mode": mode_name, "text": value.strip()})

    return [
        chip
        for chip in candidates
        if _looks_like_question(chip["text"]) and _looks_complete(chip["text"])
    ]
