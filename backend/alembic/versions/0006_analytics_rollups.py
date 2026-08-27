"""analytics rollup tables

Revision ID: 006_analytics_rollups
Revises: 005_assignment_lock_index
Create Date: 2026-05-13 12:00:00.000000

Phase 6 — adds two daily rollup tables that the API reads from:

  * ``analytics_daily_metrics`` — one row per UTC date, account-wide totals
    (AI spend, message cost, send/receive counts, response rate).
  * ``analytics_campaign_daily_metrics`` — one row per (campaign_id, date)
    with revenue / ROI / cost / response metrics.

Both are populated by ``analytics.tasks.aggregate_daily_metrics_task`` via
``INSERT ... ON CONFLICT ... DO UPDATE`` so re-running for any historical
date is idempotent.

No FKs to ``campaigns`` — these are snapshot tables; deleting a campaign
must not erase its historical performance row.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "006_analytics_rollups"
down_revision = "005_assignment_lock_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_daily_metrics",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("ai_spend_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("ai_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_avg_latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "message_cost_usd", sa.Numeric(12, 4), nullable=False, server_default="0"
        ),
        sa.Column("messages_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_delivered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_rate", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("ai_handled_pct", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("metric_date", name="uq_analytics_daily_metrics_metric_date"),
    )
    op.create_index(
        "ix_analytics_daily_metrics_metric_date",
        "analytics_daily_metrics",
        ["metric_date"],
    )
    op.create_index(
        "ix_analytics_daily_metrics_created_at",
        "analytics_daily_metrics",
        ["created_at"],
    )

    op.create_table(
        "analytics_campaign_daily_metrics",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "campaign_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("recipients_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "recipients_delivered", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("recipients_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "recipients_responded", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("response_rate", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("conversion_rate", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column(
            "revenue_attributed_usd",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("ai_spend_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column(
            "message_cost_usd", sa.Numeric(12, 4), nullable=False, server_default="0"
        ),
        sa.Column("total_cost_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("roi", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "metric_date",
            name="uq_analytics_campaign_daily_campaign_date",
        ),
    )
    op.create_index(
        "ix_analytics_campaign_daily_campaign_date",
        "analytics_campaign_daily_metrics",
        ["campaign_id", "metric_date"],
    )
    op.create_index(
        "ix_analytics_campaign_daily_metric_date",
        "analytics_campaign_daily_metrics",
        ["metric_date"],
    )
    op.create_index(
        "ix_analytics_campaign_daily_created_at",
        "analytics_campaign_daily_metrics",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analytics_campaign_daily_created_at",
        table_name="analytics_campaign_daily_metrics",
    )
    op.drop_index(
        "ix_analytics_campaign_daily_metric_date",
        table_name="analytics_campaign_daily_metrics",
    )
    op.drop_index(
        "ix_analytics_campaign_daily_campaign_date",
        table_name="analytics_campaign_daily_metrics",
    )
    op.drop_table("analytics_campaign_daily_metrics")

    op.drop_index(
        "ix_analytics_daily_metrics_created_at",
        table_name="analytics_daily_metrics",
    )
    op.drop_index(
        "ix_analytics_daily_metrics_metric_date",
        table_name="analytics_daily_metrics",
    )
    op.drop_table("analytics_daily_metrics")
