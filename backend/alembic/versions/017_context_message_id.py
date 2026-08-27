"""Add messages.context_message_id for reply/forward threading.

NULL = top-level message.
NOT NULL + same conversation_id = reply.
NOT NULL + different conversation_id = forward.
SET NULL on parent delete so child messages survive.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "017_context_message_id"
down_revision = "016_media_assets_msg_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("context_message_id", sa.UUID(as_uuid=True),
                  sa.ForeignKey("messages.id", ondelete="SET NULL"),
                  nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "context_message_id")
