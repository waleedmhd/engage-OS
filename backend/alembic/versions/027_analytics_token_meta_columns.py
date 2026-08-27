"""Add meta_cost_aed, tokens_input, tokens_output columns to existing rollup tables.

- analytics_daily_metrics: meta_cost_aed + tokens_input + tokens_output
- analytics_campaign_daily_metrics: meta_cost_aed + tokens_input + tokens_output
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "027_analytics_token_meta_columns"
down_revision = "026_analytics_template_hourly"


def _add_columns(table: str) -> None:
    op.add_column(
        table,
        sa.Column("meta_cost_aed", sa.Numeric(12, 4), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        table,
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        table,
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def upgrade() -> None:
    _add_columns("analytics_daily_metrics")
    _add_columns("analytics_campaign_daily_metrics")


def downgrade() -> None:
    for col_name in ["meta_cost_aed", "tokens_input", "tokens_output"]:
        op.drop_column("analytics_campaign_daily_metrics", col_name)
        op.drop_column("analytics_daily_metrics", col_name)
