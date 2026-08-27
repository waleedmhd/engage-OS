"""Message model (DSD §5)."""


import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.messaging.constants import (
    MessageDeliveryStatus,
    MessageDirection,
    MessageType,
    SenderType,
)

if TYPE_CHECKING:
    from app.modules.conversations.models import Conversation
    from app.modules.media.models import MediaAsset


class Message(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        enum_check("direction", MessageDirection, "ck_messages_direction_valid"),
        enum_check("sender_type", SenderType, "ck_messages_sender_type_valid"),
        enum_check(
            "delivery_status", MessageDeliveryStatus, "ck_messages_delivery_status_valid"
        ),
        enum_check("msg_type", MessageType, "ck_messages_msg_type_valid"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_delivery_status_created", "delivery_status", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    meta_message_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    delivery_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=MessageDeliveryStatus.PENDING.value,
    )
    cost: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delivery_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Outbound template sends (agent-initiated "new message"). When set, the
    # outbound dispatch task sends via Meta's template message type
    # (send_template) instead of free-form text (send_text). NULL for all
    # ordinary inbound/free-form outbound messages.
    template_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    template_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    msg_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default="text")
    context_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    deleted_by: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    deleted_for_everyone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
    media: Mapped[list["MediaAsset"]] = relationship(
        "MediaAsset", back_populates="message", lazy="selectin"
    )
    # Self-referencing: the message this one replies to or forwards from.
    context_message: Mapped["Message | None"] = relationship(
        "Message", remote_side="[Message.id]", foreign_keys=[context_message_id], lazy="selectin"
    )
