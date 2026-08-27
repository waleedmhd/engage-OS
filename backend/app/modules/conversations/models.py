"""Conversation model (DSD §5, §4.2 state machine, §4.8 lock)."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.conversations.constants import ConversationState

if TYPE_CHECKING:
    from app.modules.ai.models import AIEvent
    from app.modules.auth.models import User
    from app.modules.contacts.models import Contact
    from app.modules.messaging.models import Message


class Conversation(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        enum_check("state", ConversationState, "ck_conversations_state_valid"),
        Index("ix_conversations_state_last_message", "state", "last_message_at"),
        Index("ix_conversations_contact_state", "contact_id", "state"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=ConversationState.NEW.value,
        index=True,
    )
    outreach_state: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    ai_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    locked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    contact: Mapped["Contact"] = relationship("Contact", back_populates="conversations")
    lock_holder: Mapped["User | None"] = relationship(
        "User", back_populates="locked_conversations", foreign_keys=[locked_by]
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    ai_events: Mapped[list["AIEvent"]] = relationship(
        "AIEvent", back_populates="conversation", cascade="all, delete-orphan"
    )
