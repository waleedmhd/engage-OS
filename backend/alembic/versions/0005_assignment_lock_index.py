"""assignment lock-expiry partial index

Revision ID: 005_assignment_lock_index
Revises: 004_campaign_lifecycle
Create Date: 2026-05-13 00:00:00.000000

Phase 5.5 — supports `assignments.tasks.expire_stale_locks_task` which sweeps
expired conversation locks every 30 seconds. The sweep query is:

    SELECT id, locked_by FROM conversations
    WHERE locked_by IS NOT NULL
      AND lock_expires_at < now()
    ORDER BY lock_expires_at
    LIMIT 200
    FOR UPDATE SKIP LOCKED;

Without an index, this is a sequential scan on `conversations` every tick.
A *partial* index on `lock_expires_at` filtered by `locked_by IS NOT NULL`
makes the scan touch only currently-locked rows — typically a tiny fraction
of the table — and keeps the index itself small.

Online-safe: pure index creation, no data rewrite. At current scale plain
CREATE INDEX is fast enough; if/when conversations grows large, switch to
CREATE INDEX CONCURRENTLY (must run outside a transaction — use
`op.execute` inside an autocommit block).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "005_assignment_lock_index"
down_revision = "004_campaign_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_lock_expires_at_active",
        "conversations",
        ["lock_expires_at"],
        postgresql_where=sa.text("locked_by IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversations_lock_expires_at_active",
        table_name="conversations",
    )
