"""Add missing server defaults to the analytics rollup tables.

026_analytics_template_hourly created ``analytics_template_daily_metrics`` and
``analytics_hourly_metrics`` with ``id``, ``created_at`` and ``updated_at``
declared NOT NULL but with no server default, while the models
(UUIDPKMixin + TimestampMixin) declare all three. The aggregators insert via
raw SQL that names only the metric columns, so every insert into either table
failed with NotNullViolation on ``id``.

The other two rollup tables (analytics_daily_metrics,
analytics_campaign_daily_metrics) already carry these defaults, which is why
only these two were affected.

Revision ID: 039_analytics_rollup_defaults
Revises: 038_bill_line_unit_cost
"""

from alembic import op

revision = "039_analytics_rollup_defaults"
down_revision = "038_bill_line_unit_cost"
branch_labels = None
depends_on = None

_TABLES = ("analytics_template_daily_metrics", "analytics_hourly_metrics")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now()")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at SET DEFAULT now()")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at DROP DEFAULT")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at DROP DEFAULT")
