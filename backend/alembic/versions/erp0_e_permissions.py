"""ERP-0 Revision E — permission tables + seed permission codes.

Creates erp_permissions (code registry) and user_permissions (grant table).
Seeds all 30 ERP permission codes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "erp0_e_permissions"
down_revision = "erp0_d_contacts_finance"
branch_labels = None
depends_on = None

_PERMISSION_SEEDS: list[tuple[str, str, str]] = [
    ("journal.post", "Create and post manual journal entries", "ledger"),
    ("journal.reverse", "Reverse posted journal entries", "ledger"),
    ("coa.manage", "Create, edit, and deactivate chart of accounts entries", "ledger"),
    ("period.manage", "Open and close fiscal periods", "ledger"),
    ("period.reopen", "Reopen a closed or locked fiscal period", "ledger"),
    ("erp_ar.invoice.create", "Create sales invoices", "receivables"),
    ("erp_ar.invoice.void", "Void issued invoices", "receivables"),
    ("erp_ar.payment.create", "Record customer payments", "receivables"),
    ("erp_ar.payment.allocate", "Allocate payments to invoices", "receivables"),
    ("erp_ar.credit_note.create", "Issue credit notes", "receivables"),
    ("erp_ap.bill.create", "Create supplier bills", "payables"),
    ("erp_ap.bill.void", "Void issued bills", "payables"),
    ("erp_ap.payment.create", "Record supplier payments", "payables"),
    ("erp_ap.payment.allocate", "Allocate payments to bills", "payables"),
    ("erp_ap.debit_note.create", "Issue debit notes", "payables"),
    ("item.manage", "Create, edit, and deactivate items", "inventory"),
    ("stock.view", "View stock on hand and serial lookups", "inventory"),
    ("stock.adjust", "Create stock adjustments (write-offs, gains)", "inventory"),
    ("stock.transfer", "Create stock transfers between locations", "inventory"),
    ("stock.count", "Create and confirm stock counts", "inventory"),
    ("erp_proc.po.create", "Create purchase orders", "procurement"),
    ("erp_proc.po.approve", "Approve purchase orders", "procurement"),
    ("erp_proc.grn.create", "Create goods receipt notes (GRNs)", "procurement"),
    ("erp_ful.so.create", "Create sales orders", "fulfilment"),
    ("erp_ful.so.approve", "Approve sales orders", "fulfilment"),
    ("erp_ful.dispatch.create", "Create dispatch / delivery notes", "fulfilment"),
    ("erp_rep.statements.view", "View Trial Balance, P&L, Balance Sheet", "erp_reporting"),
    ("erp_rep.ageing.view", "View AR and AP ageing reports", "erp_reporting"),
    ("erp_rep.margin.view", "View margin and profitability reports", "erp_reporting"),
    ("erp_rep.settings.manage", "Manage ERP settings", "erp_reporting"),
]


def upgrade() -> None:
    op.create_table(
        "erp_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("module", sa.String(50), nullable=False),
    )
    op.create_index("ix_erp_permissions_module", "erp_permissions", ["module"])

    op.create_table(
        "user_permissions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, primary_key=True),
        sa.Column("permission_code", sa.String(100),
                  sa.ForeignKey("public.erp_permissions.code", ondelete="CASCADE"),
                  nullable=False, primary_key=True),
    )
    op.create_index("ix_user_permissions_user", "user_permissions", ["user_id"])
    op.create_index("ix_user_permissions_code", "user_permissions", ["permission_code"])

    # Seed permission codes.
    for code, description, module in _PERMISSION_SEEDS:
        op.execute(
            sa.text(
                "INSERT INTO erp_permissions (id, code, description, module) "
                "VALUES (gen_random_uuid(), :code, :description, :module) "
                "ON CONFLICT (code) DO NOTHING"
            ).bindparams(code=code, description=description, module=module)
        )


def downgrade() -> None:
    op.drop_table("user_permissions")
    op.drop_table("erp_permissions")
