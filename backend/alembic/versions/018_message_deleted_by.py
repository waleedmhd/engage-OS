"""Add messages.deleted_by (JSONB) and deleted_for_everyone (bool).

Batch 3 — Bulk Operations:
  - deleted_by: {"agent_id": "2026-06-10T14:30:00Z"} for agent-only delete;
    {"agent_id": "...", "contact": "..."} when both parties delete.
  - deleted_for_everyone: TRUE when the agent sends a Meta delete request.

Both are NULL-safe. deleted_by=NULL means not deleted.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "018_message_deleted_by"
down_revision = "017_context_message_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("deleted_by", sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column(
        "messages",
        sa.Column("deleted_for_everyone", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("messages", "deleted_for_everyone")
    op.drop_column("messages", "deleted_by")
