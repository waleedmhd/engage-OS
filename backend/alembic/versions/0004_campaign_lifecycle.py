"""Campaign lifecycle: scheduling, throttling, compliance, delivery tracking.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-10 00:00:00.000000

Phase 4 (Campaign system): adds the columns and indexes required to drive
the campaign lifecycle manager — recurring schedule fields, audience filter
snapshot, throttle override, compliance validation results, timing markers,
and per-recipient delivery linkage to the messaging pipeline.

Online-safe: all columns are nullable or have a server_default so existing
rows pick up safe values without rewrite.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "004_campaign_lifecycle"
down_revision = "003_ai_draft_message_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----------------------------------------------------------------- contacts
    op.add_column(
        "contacts",
        sa.Column(
            "marketing_opt_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_contacts_marketing_opt_out",
        "contacts",
        ["marketing_opt_out"],
    )

    # ---------------------------------------------------------------- campaigns
    op.add_column(
        "campaigns",
        sa.Column("cron_expression", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "audience_filter",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "campaigns",
        sa.Column("rate_limit_per_second", sa.Integer(), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "validation_errors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "campaigns",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
     
    op.create_index(
        "ix_campaigns_next_run_at",
        "campaigns",
        ["next_run_at"],
    )
    op.create_index(
        "ix_campaigns_type_next_run_at",
        "campaigns",
        ["campaign_type", "next_run_at"],
    )

    # ------------------------------------------------------- campaign_recipients
    op.add_column(
        "campaign_recipients",
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "campaign_recipients",
        sa.Column("meta_message_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "campaign_recipients",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "campaign_recipients",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index(
        "ix_campaign_recipients_message_id",
        "campaign_recipients",
        ["message_id"],
    )
    op.create_index(
        "ix_campaign_recipients_meta_message_id",
        "campaign_recipients",
        ["meta_message_id"],
    )


def downgrade() -> None:
    # -------------------------------------------------------- campaign_recipients
    op.drop_index(
        "ix_campaign_recipients_meta_message_id",
        table_name="campaign_recipients",
    )
    op.drop_index(
        "ix_campaign_recipients_message_id",
        table_name="campaign_recipients",
    )
    op.drop_column("campaign_recipients", "attempt_count")
    op.drop_column("campaign_recipients", "failed_at")
    op.drop_column("campaign_recipients", "meta_message_id")
    op.drop_column("campaign_recipients", "message_id")

    # ---------------------------------------------------------------- campaigns
    op.drop_index("ix_campaigns_type_next_run_at", table_name="campaigns")
    op.drop_index("ix_campaigns_next_run_at", table_name="campaigns")
    op.drop_column("campaigns", "completed_at")
    op.drop_column("campaigns", "started_at")
    op.drop_column("campaigns", "validation_errors")
    op.drop_column("campaigns", "rate_limit_per_second")
    op.drop_column("campaigns", "audience_filter")
    op.drop_column("campaigns", "last_run_at")
    op.drop_column("campaigns", "next_run_at")
    op.drop_column("campaigns", "cron_expression")

    # ----------------------------------------------------------------- contacts
    op.drop_index("ix_contacts_marketing_opt_out", table_name="contacts")
    op.drop_column("contacts", "marketing_opt_out")
