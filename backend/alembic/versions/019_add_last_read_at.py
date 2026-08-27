"""Add conversations.last_read_at for inbox unread tracking.

When an agent opens a conversation thread, last_read_at is set to now().
The inbox query compares last_message_at against last_read_at to determine
whether the conversation has unread inbound messages (for the unread dot /
bold styling in the frontend).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "019_add_last_read_at"
down_revision = "018_message_deleted_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "last_read_at")
