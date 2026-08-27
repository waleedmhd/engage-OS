"""Add error_code to messages and campaign_recipients for structured failure diagnostics.

Meta Cloud API failures carry numeric error codes (131026 = undeliverable,
131047 = opted out, 131052 = not on WhatsApp, etc.) alongside human-readable
messages. Storing them in a typed column lets the API surface both to agents
so they can understand *why* a message failed instead of just seeing "failed".
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "020_add_error_code"
down_revision = "019_add_last_read_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("error_code", sa.Integer(), nullable=True),
    )
    op.add_column(
        "campaign_recipients",
        sa.Column("error_code", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaign_recipients", "error_code")
    op.drop_column("messages", "error_code")
