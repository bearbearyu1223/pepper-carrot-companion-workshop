"""SQLAlchemy 2.0 typed declarative models.

See docs/data-model.md for the rationale behind each table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Common base for all ORM models."""


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


def _timestamp_now() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    episode_number: Mapped[int] = mapped_column(nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    cover_image_url: Mapped[str | None] = mapped_column(Text)
    plot_summary: Mapped[str | None] = mapped_column(Text)
    credits_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = _timestamp_now()

    pages: Mapped[list[Page]] = relationship(
        back_populates="episode", cascade="all, delete-orphan", order_by="Page.page_number"
    )
    commentary_notes: Mapped[list[CommentaryNote]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("episode_id", "page_number", name="uq_pages_episode_page"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    original_url: Mapped[str | None] = mapped_column(Text)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    visual_description: Mapped[str | None] = mapped_column(Text)
    mood_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    image_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    episode: Mapped[Episode] = relationship(back_populates="pages")
    characters: Mapped[list[Character]] = relationship(
        secondary="page_characters", back_populates="pages"
    )


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    bio: Mapped[str | None] = mapped_column(Text)
    first_appearance_episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="SET NULL")
    )
    image_url: Mapped[str | None] = mapped_column(Text)

    pages: Mapped[list[Page]] = relationship(
        secondary="page_characters", back_populates="characters"
    )


class PageCharacter(Base):
    __tablename__ = "page_characters"

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True
    )


class WikiArticle(Base):
    __tablename__ = "wiki_articles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)


class CommentaryNote(Base):
    __tablename__ = "commentary_notes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    page_number_hint: Mapped[int | None] = mapped_column()
    source_url: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    episode: Mapped[Episode] = relationship(back_populates="commentary_notes")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str | None] = mapped_column(String(256))
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    current_page: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = _timestamp_now()

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class WorldEntity(Base):
    __tablename__ = "world_entities"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    episode_debut: Mapped[int] = mapped_column(nullable=False)
    page_debut: Mapped[int] = mapped_column(nullable=False)
    layout_x: Mapped[float] = mapped_column(Float, nullable=False)
    layout_y: Mapped[float] = mapped_column(Float, nullable=False)
    character_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("characters.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class WorldRelationship(Base):
    __tablename__ = "world_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "target_id", "kind", name="uq_world_relationships_src_tgt_kind"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("world_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("world_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    episode_debut: Mapped[int] = mapped_column(nullable=False)
    page_debut: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = _timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_created", "session_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # 'user' | 'assistant'
    mode: Mapped[str | None] = mapped_column(String(32))  # null on user messages OK
    content: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_doc_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    latency_ms: Mapped[int | None] = mapped_column()
    token_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _timestamp_now()

    session: Mapped[ChatSession] = relationship(back_populates="messages")
