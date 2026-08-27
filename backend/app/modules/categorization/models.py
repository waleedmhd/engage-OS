"""Tag, ContactTag (M2M), TagSuggestion (DSD §5, §4.6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.categorization.constants import TagSuggestionStatus

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.contacts.models import Contact


class Tag(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    contact_links: Mapped[list[ContactTag]] = relationship(
        "ContactTag", back_populates="tag", cascade="all, delete-orphan"
    )
    suggestions: Mapped[list[TagSuggestion]] = relationship(
        "TagSuggestion", back_populates="tag", cascade="all, delete-orphan"
    )


class ContactTag(Base):
    __tablename__ = "contact_tags"
    __table_args__ = (
        PrimaryKeyConstraint("contact_id", "tag_id", name="pk_contact_tags"),
        Index("ix_contact_tags_tag_id", "tag_id"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contact: Mapped[Contact] = relationship("Contact", back_populates="contact_tags")
    tag: Mapped[Tag] = relationship("Tag", back_populates="contact_links")
    approver: Mapped[User | None] = relationship("User", foreign_keys=[approved_by])


class TagSuggestion(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tag_suggestions"
    __table_args__ = (
        enum_check("status", TagSuggestionStatus, "ck_tag_suggestions_status_valid"),
        Index("ix_tag_suggestions_status_created_at", "status", "created_at"),
        Index("ix_tag_suggestions_contact_status", "contact_id", "status"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=TagSuggestionStatus.PENDING.value,
        index=True,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contact: Mapped[Contact] = relationship("Contact", back_populates="tag_suggestions")
    tag: Mapped[Tag] = relationship("Tag", back_populates="suggestions")
    reviewer: Mapped[User | None] = relationship("User", foreign_keys=[reviewed_by])
