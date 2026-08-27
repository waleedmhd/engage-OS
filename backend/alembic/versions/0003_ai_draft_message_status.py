"""Add 'draft' to messages.delivery_status CHECK constraint.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-10 00:00:00.000000

Phase 2 (AI Integration): AI-authored reply drafts awaiting human approval
are persisted as Message rows with delivery_status='draft'. This status must
be added to the DB CHECK constraint and the SQLAlchemy enum before it can
be inserted.

Migration strategy (online-safe):
  1. DROP the existing CHECK constraint (ck_messages_delivery_status).
  2. ADD a new CHECK constraint that includes 'draft'.
  Both operations are metadata-only on the constraint; no row rewrite is
  required.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "003_ai_draft_message_status"
down_revision = "002_crm_core_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old constraint, then recreate with 'draft' included.
    op.drop_constraint("ck_messages_delivery_status", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_delivery_status",
        "messages",
        "delivery_status IN ('draft', 'queued', 'sent', 'delivered', 'read', 'failed')",
    )


def downgrade() -> None:
    # Remove 'draft' rows first to restore the narrower constraint safely.
    op.execute(
        "DELETE FROM messages WHERE delivery_status = 'draft'"
    )
    op.drop_constraint("ck_messages_delivery_status", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_delivery_status",
        "messages",
        "delivery_status IN ('queued', 'sent', 'delivered', 'read', 'failed')",
    )
