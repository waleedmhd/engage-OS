"""Campaign + CampaignRecipient models (DSD §5, §4.7)."""


import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.campaigns.constants import (
    CampaignRecipientStatus,
    CampaignStatus,
    CampaignType,
)

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.contacts.models import Contact
    from app.modules.templates.models import Template


class Campaign(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        enum_check("status", CampaignStatus, "ck_campaigns_status_valid"),
        enum_check("type", CampaignType, "ck_campaigns_type_valid"),
        Index("ix_campaigns_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_campaigns_type_next_run_at", "type", "next_run_at"),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=CampaignStatus.DRAFT.value, index=True
    )
    type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=CampaignType.IMMEDIATE.value
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    audience_filter: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    rate_limit_per_second: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_errors: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    audience_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    response_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaign_categories.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    template: Mapped["Template"] = relationship("Template", back_populates="campaigns")
    creator: Mapped["User | None"] = relationship("User", foreign_keys=[created_by])
    category: Mapped["CampaignCategory | None"] = relationship(
        "CampaignCategory", foreign_keys=[category_id]
    )
    recipients: Mapped[list["CampaignRecipient"]] = relationship(
        "CampaignRecipient", back_populates="campaign", cascade="all, delete-orphan"
    )


class CampaignRecipient(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", name="uq_campaign_recipients_campaign_contact"),
        enum_check(
            "status", CampaignRecipientStatus, "ck_campaign_recipients_status_valid"
        ),
        Index("ix_campaign_recipients_campaign_status", "campaign_id", "status"),
        Index("ix_campaign_recipients_meta_message_id", "meta_message_id"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=CampaignRecipientStatus.PENDING.value,
    )
    outreach_state: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    responded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="recipients")
    contact: Mapped["Contact"] = relationship("Contact")


class CampaignCategory(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "campaign_categories"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
