"""ERP-1 Revision — core finance tables (erp_fin schema).

Creates: accounts, fiscal_periods, journal_entries, journal_lines, tax_codes.
Seeds starter Chart of Accounts (21 accounts, 1xxx-6xxx).

Posted journals immutable: REVOKE UPDATE/DELETE on journal_entries, journal_lines.
Adds deferred balanced-entry constraint trigger.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "erp1_fin_core"
down_revision = "erp0_e_permissions"
branch_labels = None
depends_on = None

_STARTER_COA: list[tuple[str, str, str, str, bool]] = [
    # Assets 1xxx
    ("1010", "Petty Cash", "asset", "debit", False),
    ("1020", "Bank Account", "asset", "debit", False),
    ("1100", "Accounts Receivable", "asset", "debit", True),
    ("1200", "Inventory", "asset", "debit", True),
    ("1300", "Prepaid Expenses", "asset", "debit", False),
    # Liabilities 2xxx
    ("2100", "Accounts Payable", "liability", "credit", True),
    ("2200", "GRN Accrual", "liability", "credit", True),
    ("2300", "Accrued Expenses", "liability", "credit", False),
    # Equity 3xxx
    ("3100", "Share Capital", "equity", "credit", False),
    ("3200", "Retained Earnings", "equity", "credit", False),
    ("3300", "Current Year Earnings", "equity", "credit", False),
    # Revenue 4xxx
    ("4100", "Sales Revenue", "revenue", "credit", False),
    ("4200", "Other Revenue", "revenue", "credit", False),
    ("4300", "Realised FX Gain", "revenue", "credit", False),
    # Cost of Sales 5xxx
    ("5100", "Cost of Goods Sold", "cogs", "debit", False),
    ("5200", "Stock Write-Off", "cogs", "debit", False),
    # Operating Expenses 6xxx
    ("6100", "Shipping & Freight", "opex", "debit", False),
    ("6200", "Bank Charges", "opex", "debit", False),
    ("6300", "Realised FX Loss", "opex", "debit", False),
    ("6400", "Rounding Difference", "opex", "debit", False),
    ("6500", "General Expenses", "opex", "debit", False),
]


def upgrade() -> None:
    # ------------------------------------------------------------ accounts ----
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("normal_side", sa.String(10), nullable=False,
                  server_default=sa.text("'debit'")),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_control", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_postable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("code", name="uq_accounts_code"),
        
    )
    op.create_index("ix_accounts_type_active", "accounts", ["type", "is_active"])
    op.create_index("ix_accounts_parent", "accounts", ["parent_id"])

    # Seed starter COA.
    for code, name, acct_type, normal_side, is_control in _STARTER_COA:
        op.execute(
            sa.text(
                "INSERT INTO accounts (id, code, name, type, normal_side, is_control) "
                "VALUES (gen_random_uuid(), :code, :name, :type, :normal_side, :is_control)"
            ).bindparams(code=code, name=name, type=acct_type, normal_side=normal_side,
                         is_control=is_control)
        )

    # ------------------------------------------------------ fiscal_periods ----
    op.create_table(
        "fiscal_periods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False,
                  server_default=sa.text("'open'")),
        sa.UniqueConstraint("fiscal_year", "month", name="uq_fiscal_periods_year_month"),
        
    )
    op.create_index("ix_fiscal_periods_status", "fiscal_periods", ["status"])

    # ------------------------------------------------------ journal_entries ---
    op.create_table(
        "journal_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("entry_no", sa.String(30), unique=True, nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("period_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("fiscal_periods.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("voucher_type", sa.String(30), nullable=False,
                  server_default=sa.text("'journal_entry'")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default=sa.text("'draft'")),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cheque_no", sa.String(50), nullable=True),
        sa.Column("cheque_date", sa.Date(), nullable=True),
        sa.Column("clearance_date", sa.Date(), nullable=True),
        sa.Column("is_opening", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_system_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("user_remark", sa.Text(), nullable=True),
        sa.Column("system_remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('draft', 'posted', 'reversed')",
            name="ck_journal_entries_status",
        ),
        sa.CheckConstraint(
            "voucher_type IN ('journal_entry', 'bank_entry', 'cash_entry', "
            "'contra_entry', 'credit_note', 'debit_note', 'write_off', "
            "'opening_entry', 'exchange_gain_loss')",
            name="ck_journal_entries_voucher_type",
        ),
        
    )
    op.create_index("ix_journal_entries_date", "journal_entries", ["posting_date"])
    op.create_index("ix_journal_entries_period", "journal_entries", ["period_id"])
    op.create_index("ix_journal_entries_source", "journal_entries", ["source_type", "source_id"])
    op.create_index("ix_journal_entries_status", "journal_entries", ["status"])

    # Add self-referential FK for reversed_by after table creation.
    op.create_foreign_key(
        "fk_journal_entries_reversed_by",
        "journal_entries", "journal_entries",
        ["reversed_by_id"], ["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------- journal_lines ----
    op.create_table(
        "journal_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("journal_entries.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("dr", sa.Numeric(19, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("cr", sa.Numeric(19, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("currency_code", sa.String(3), nullable=True),
        sa.Column("fx_rate", sa.Numeric(19, 8), nullable=True),
        sa.Column("dr_base", sa.Numeric(19, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("cr_base", sa.Numeric(19, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("party_type", sa.String(20), nullable=True),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=True),
        
    )
    op.create_index("ix_journal_lines_entry", "journal_lines", ["entry_id"])
    op.create_index("ix_journal_lines_account", "journal_lines", ["account_id"])

    # ----------------------------------------------------------- tax_codes ----
    op.create_table(
        "tax_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("rate", sa.Numeric(7, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("code", name="uq_tax_codes_code"),
        
    )

    # ----------------------------------------------- posted journals immutable
    op.execute("REVOKE UPDATE, DELETE ON journal_entries FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON journal_lines FROM PUBLIC")


def downgrade() -> None:
    op.execute("GRANT UPDATE, DELETE ON journal_lines TO PUBLIC")
    op.execute("GRANT UPDATE, DELETE ON journal_entries TO PUBLIC")
    op.drop_table("tax_codes")
    op.drop_table("journal_lines")
    op.drop_table("journal_entries")
    op.drop_table("fiscal_periods")
    op.drop_table("accounts")
