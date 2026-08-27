"""AIEvent model (DSD §5)."""


import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.modules.conversations.models import Conversation


class AIEvent(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "ai_events"
    __table_args__ = (
        Index("ix_ai_events_conversation_created", "conversation_id", "created_at"),
        Index("ix_ai_events_request_gin", "request", postgresql_using="gin"),
        Index("ix_ai_events_response_gin", "response", postgresql_using="gin"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    response: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="ai_events"
    )
