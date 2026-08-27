"""Add Message.template_name / template_language for agent-initiated template sends.

Additive only. Both columns are nullable with no backfill: every existing
message is a free-form (send_text) message, which the dispatch task continues
to handle when these columns are NULL. When set (by the new
POST /messages/start flow), the outbound task sends via Meta's template
message type (send_template).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "013_message_template_fields"
down_revision = "012_template_status_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("template_name", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("template_language", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "template_language")
    op.drop_column("messages", "template_name")
