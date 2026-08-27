"""Analytics rollup tables (Phase 6).

Snapshot tables populated by `analytics.tasks.aggregate_daily_metrics_task`.
They are read-only from the API's perspective: the source-of-truth tables
(`ai_events`, `messages`, `campaign_recipients`, `contacts`) remain
authoritative; these rows just exist so dashboard endpoints don't have to
re-aggregate millions of rows on every request.

No FKs to `campaigns` — deleting a campaign should not erase historical
performance numbers. Stale campaign_ids in the rollups are tolerable.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date as SADate
from sqlalchemy import Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class AnalyticsDailyMetrics(UUIDPKMixin, TimestampMixin, Base):
    """One row per UTC day — account-wide totals."""

    __tablename__ = "analytics_daily_metrics"
    __table_args__ = (
        UniqueConstraint("metric_date", name="uq_analytics_daily_metrics_metric_date"),
        Index("ix_analytics_daily_metrics_metric_date", "metric_date"),
    )

    metric_date: Mapped[date] = mapped_column(SADate, nullable=False)

    ai_spend_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    ai_call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ai_error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ai_avg_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    message_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    meta_cost_aed: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    messages_sent: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    messages_delivered: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    messages_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    messages_received: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    response_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="0"
    )
    ai_handled_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="0"
    )
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )


class AnalyticsCampaignDailyMetrics(UUIDPKMixin, TimestampMixin, Base):
    """One row per (campaign_id, day) — per-campaign performance."""

    __tablename__ = "analytics_campaign_daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "metric_date",
            name="uq_analytics_campaign_daily_campaign_date",
        ),
        Index(
            "ix_analytics_campaign_daily_campaign_date",
            "campaign_id",
            "metric_date",
        ),
        Index("ix_analytics_campaign_daily_metric_date", "metric_date"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_date: Mapped[date] = mapped_column(SADate, nullable=False)

    recipients_sent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    recipients_delivered: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    recipients_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    recipients_responded: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    response_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="0"
    )
    conversion_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="0"
    )

    revenue_attributed_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    ai_spend_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    message_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    meta_cost_aed: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    roi: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)


class AnalyticsTemplateDailyMetrics(UUIDPKMixin, TimestampMixin, Base):
    """One row per (template_id, day) — per-template performance.

    Only templates that have been used in at least one campaign are included.
    template_name is denormalized so historical data survives template deletion.
    """

    __tablename__ = "analytics_template_daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "metric_date",
            name="uq_analytics_template_daily_template_date",
        ),
        Index(
            "ix_analytics_template_daily_template_date",
            "template_id",
            "metric_date",
        ),
        Index("ix_analytics_template_daily_metric_date", "metric_date"),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    template_name: Mapped[str] = mapped_column(
        String(200), nullable=False, server_default=""
    )
    metric_date: Mapped[date] = mapped_column(SADate, nullable=False)

    campaigns_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    recipients_sent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    recipients_delivered: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    recipients_responded: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    response_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="0"
    )
    message_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    meta_cost_aed: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    ai_spend_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )


class AnalyticsHourlyMetrics(UUIDPKMixin, TimestampMixin, Base):
    """One row per (metric_date, hour) — time-of-day responsiveness patterns.

    day_of_week is derived from metric_date at query time.
    """

    __tablename__ = "analytics_hourly_metrics"
    __table_args__ = (
        UniqueConstraint(
            "metric_date", "hour", name="uq_analytics_hourly_metrics_date_hour"
        ),
        Index("ix_analytics_hourly_metrics_metric_date", "metric_date"),
    )

    metric_date: Mapped[date] = mapped_column(SADate, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)

    messages_sent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    messages_received: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    response_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="0"
    )
