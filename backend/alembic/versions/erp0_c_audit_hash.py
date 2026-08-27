"""ERP-0 Revision C — add hash-chain columns to existing audit_logs table.

Adds prev_hash and row_hash (both nullable VARCHAR(64)) to audit_logs.
Existing CRM entries have NULL hashes — the chain starts at the first ERP-era
entry. verify_chain() recomputes hashes for all rows with non-NULL row_hash
and detects after-the-fact tampering.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "erp0_c_audit_hash"
down_revision = "erp0_b_erp_schemas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("prev_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("row_hash", sa.String(64), nullable=True))
    op.create_index("ix_audit_logs_row_hash", "audit_logs", ["row_hash"],
                    postgresql_where=sa.text("row_hash IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_audit_logs_row_hash", table_name="audit_logs",
                  postgresql_where=sa.text("row_hash IS NOT NULL"))
    op.drop_column("audit_logs", "row_hash")
    op.drop_column("audit_logs", "prev_hash")
