"""Add missing tag_suggestions.updated_at (TimestampMixin drift).

MA-12 (0007) added updated_at to refresh_tokens / tags / audit_logs but
missed tag_suggestions, which also inherits TimestampMixin. The ORM emits
``RETURNING tag_suggestions.updated_at`` on every insert, so without this
column every TagSuggestion write (AI categorization decision-engine path)
fails with UndefinedColumn in production.

Online-safe: nullable=False with a server_default so existing rows backfill.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "008_tag_suggestions_updated_at"
down_revision = "007_model_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tag_suggestions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tag_suggestions", "updated_at")
