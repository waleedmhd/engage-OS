"""Add analytics_template_daily_metrics and analytics_hourly_metrics rollup tables.

Template metrics track per-template performance (only templates that have been
used in campaigns). Hourly metrics capture time-of-day and day-of-week
responsiveness patterns.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "026_analytics_template_hourly"
down_revision = "025_client_memories"


def upgrade() -> None:
    op.create_table(
        "analytics_template_daily_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("campaigns_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipients_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipients_delivered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipients_responded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_rate", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("message_cost_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("meta_cost_aed", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("ai_spend_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "metric_date", name="uq_analytics_template_daily_template_date"),
        sa.Index("ix_analytics_template_daily_template_date", "template_id", "metric_date"),
        sa.Index("ix_analytics_template_daily_metric_date", "metric_date"),
        keep_existing=False,
    )

    op.create_table(
        "analytics_hourly_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("hour", sa.SmallInteger(), nullable=False),
        sa.Column("messages_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_rate", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("metric_date", "hour", name="uq_analytics_hourly_metrics_date_hour"),
        sa.Index("ix_analytics_hourly_metrics_metric_date", "metric_date"),
        keep_existing=False,
    )


def downgrade() -> None:
    op.drop_table("analytics_hourly_metrics")
    op.drop_table("analytics_template_daily_metrics")
