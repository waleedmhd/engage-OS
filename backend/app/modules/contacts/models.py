"""Contact model (DSD §5.1)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.contacts.constants import ContactStatus

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.categorization.models import ContactTag, TagSuggestion
    from app.modules.contacts.memory_models import ClientMemory
    from app.modules.conversations.models import Conversation


class Contact(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        enum_check("status", ContactStatus, "ck_contacts_status_valid"),
        Index("ix_contacts_status_last_interaction", "status", "last_interaction_at"),
        Index("ix_contacts_assigned_agent_status", "assigned_agent_id", "status"),
    )

    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContactStatus.ACTIVE.value, index=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    information: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    revenue_attributed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    estimated_ltv: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_inbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    conversation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    marketing_opt_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", index=True
    )
    do_not_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", index=True
    )
    ai_assigned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    assigned_agent: Mapped["User | None"] = relationship(
        "User", back_populates="assigned_contacts", foreign_keys=[assigned_agent_id]
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="contact", cascade="all, delete-orphan"
    )
    contact_tags: Mapped[list["ContactTag"]] = relationship(
        "ContactTag", back_populates="contact", cascade="all, delete-orphan"
    )
    tag_suggestions: Mapped[list["TagSuggestion"]] = relationship(
        "TagSuggestion", back_populates="contact", cascade="all, delete-orphan"
    )
    memory: Mapped["ClientMemory | None"] = relationship(
        "ClientMemory", back_populates="contact", uselist=False, cascade="all, delete-orphan"
    )
