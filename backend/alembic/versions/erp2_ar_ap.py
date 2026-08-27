"""ERP-2 Revision — AR + AP tables (erp_fin schema).

Creates:
  AR: sales_invoices, sales_invoice_lines, customer_payments,
      payment_allocations, credit_notes
  AP: supplier_bills, supplier_bill_lines, supplier_payments,
      bill_allocations, debit_notes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "erp2_ar_ap"
down_revision = "erp1_fin_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================= AR tables ====

    # ------------------------------------------------------- sales_invoices ----
    op.create_table(
        "sales_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("invoice_no", sa.String(30), unique=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False,
                  server_default=sa.text("'AED'")),
        sa.Column("fx_rate", sa.Numeric(19, 8), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("subtotal", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("tax_total", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("total", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("status", sa.String(10), nullable=False,
                  server_default=sa.text("'draft'")),
        sa.Column("je_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'paid', 'overdue', 'void')",
            name="ck_sales_invoices_status",
        ),
        sa.UniqueConstraint("invoice_no", name="uq_sales_invoices_invoice_no"),
        
    )
    op.create_index("ix_sales_invoices_customer", "sales_invoices", ["customer_id"])
    op.create_index("ix_sales_invoices_status", "sales_invoices", ["status"])
    op.create_index("ix_sales_invoices_due_date", "sales_invoices", ["due_date"])

    # -------------------------------------------------- sales_invoice_lines ----
    op.create_table(
        "sales_invoice_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sales_invoices.id", ondelete="CASCADE"),
                  nullable=False),
        # item_id kept as plain UUID — erp_inv.items not yet created; FK to follow.
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.String(500), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("qty", sa.Numeric(12, 2), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("unit_price", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("line_total", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("tax_code_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tax_codes.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("tax_amount", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        
    )
    op.create_index("ix_sales_invoice_lines_invoice", "sales_invoice_lines", ["invoice_id"])

    # ----------------------------------------------------- customer_payments ----
    op.create_table(
        "customer_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("payment_no", sa.String(30), unique=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("currency_code", sa.String(3), nullable=False,
                  server_default=sa.text("'AED'")),
        sa.Column("fx_rate", sa.Numeric(19, 8), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("payment_method", sa.String(20), nullable=False,
                  server_default=sa.text("'bank_transfer'")),
        sa.Column("reference", sa.String(200), nullable=True),
        sa.Column("je_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("status", sa.String(10), nullable=False,
                  server_default=sa.text("'uncleared'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('cleared', 'uncleared', 'void')",
            name="ck_customer_payments_status",
        ),
        sa.UniqueConstraint("payment_no", name="uq_customer_payments_payment_no"),
        
    )
    op.create_index("ix_customer_payments_customer", "customer_payments", ["customer_id"])
    op.create_index("ix_customer_payments_date", "customer_payments", ["payment_date"])

    # ---------------------------------------------------- payment_allocations ----
    op.create_table(
        "payment_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("customer_payments.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sales_invoices.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.UniqueConstraint("payment_id", "invoice_id", name="uq_payment_allocations"),
        
    )
    op.create_index("ix_payment_allocations_invoice", "payment_allocations", ["invoice_id"])

    # ----------------------------------------------------------- credit_notes ----
    op.create_table(
        "credit_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("credit_note_no", sa.String(30), unique=True, nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sales_invoices.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("reason", sa.String(20), nullable=False,
                  server_default=sa.text("'other'")),
        sa.Column("currency_code", sa.String(3), nullable=False,
                  server_default=sa.text("'AED'")),
        sa.Column("fx_rate", sa.Numeric(19, 8), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("je_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("status", sa.String(10), nullable=False,
                  server_default=sa.text("'draft'")),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "reason IN ('goods_returned', 'price_adjustment', 'damaged_goods', 'other')",
            name="ck_credit_notes_reason",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'void')",
            name="ck_credit_notes_status",
        ),
        sa.UniqueConstraint("credit_note_no", name="uq_credit_notes_credit_note_no"),
        
    )
    op.create_index("ix_credit_notes_customer", "credit_notes", ["customer_id"])
    op.create_index("ix_credit_notes_invoice", "credit_notes", ["invoice_id"])

    # ============================================================= AP tables ====

    # --------------------------------------------------------- supplier_bills ----
    op.create_table(
        "supplier_bills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("bill_no", sa.String(30), unique=True, nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False,
                  server_default=sa.text("'AED'")),
        sa.Column("fx_rate", sa.Numeric(19, 8), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("subtotal", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("tax_total", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("total", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("status", sa.String(10), nullable=False,
                  server_default=sa.text("'draft'")),
        sa.Column("je_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("grn_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'paid', 'overdue', 'void')",
            name="ck_supplier_bills_status",
        ),
        sa.UniqueConstraint("bill_no", name="uq_supplier_bills_bill_no"),
        
    )
    op.create_index("ix_supplier_bills_supplier", "supplier_bills", ["supplier_id"])
    op.create_index("ix_supplier_bills_status", "supplier_bills", ["status"])
    op.create_index("ix_supplier_bills_due_date", "supplier_bills", ["due_date"])

    # ---------------------------------------------------- supplier_bill_lines ----
    op.create_table(
        "supplier_bill_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("bill_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("supplier_bills.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.String(500), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("qty", sa.Numeric(12, 2), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("unit_price", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("line_total", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("tax_code_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tax_codes.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("tax_amount", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        
    )
    op.create_index("ix_supplier_bill_lines_bill", "supplier_bill_lines", ["bill_id"])

    # ------------------------------------------------------ supplier_payments ----
    op.create_table(
        "supplier_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("payment_no", sa.String(30), unique=True, nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("currency_code", sa.String(3), nullable=False,
                  server_default=sa.text("'AED'")),
        sa.Column("fx_rate", sa.Numeric(19, 8), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("payment_method", sa.String(20), nullable=False,
                  server_default=sa.text("'bank_transfer'")),
        sa.Column("reference", sa.String(200), nullable=True),
        sa.Column("je_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("status", sa.String(10), nullable=False,
                  server_default=sa.text("'uncleared'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('cleared', 'uncleared', 'void')",
            name="ck_supplier_payments_status",
        ),
        sa.UniqueConstraint("payment_no", name="uq_supplier_payments_payment_no"),
        
    )
    op.create_index("ix_supplier_payments_supplier", "supplier_payments", ["supplier_id"])
    op.create_index("ix_supplier_payments_date", "supplier_payments", ["payment_date"])

    # ------------------------------------------------------- bill_allocations ----
    op.create_table(
        "bill_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("supplier_payments.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("bill_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("supplier_bills.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.UniqueConstraint("payment_id", "bill_id", name="uq_bill_allocations"),
        
    )
    op.create_index("ix_bill_allocations_bill", "bill_allocations", ["bill_id"])

    # ------------------------------------------------------------ debit_notes ----
    op.create_table(
        "debit_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("debit_note_no", sa.String(30), unique=True, nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("bill_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("supplier_bills.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("reason", sa.String(20), nullable=False,
                  server_default=sa.text("'other'")),
        sa.Column("currency_code", sa.String(3), nullable=False,
                  server_default=sa.text("'AED'")),
        sa.Column("fx_rate", sa.Numeric(19, 8), nullable=False,
                  server_default=sa.text("1")),
        sa.Column("je_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("status", sa.String(10), nullable=False,
                  server_default=sa.text("'draft'")),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "reason IN ('goods_returned', 'price_adjustment', 'damaged_goods', 'other')",
            name="ck_debit_notes_reason",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'void')",
            name="ck_debit_notes_status",
        ),
        sa.UniqueConstraint("debit_note_no", name="uq_debit_notes_debit_note_no"),
        
    )
    op.create_index("ix_debit_notes_supplier", "debit_notes", ["supplier_id"])
    op.create_index("ix_debit_notes_bill", "debit_notes", ["bill_id"])


def downgrade() -> None:
    # Drop AP tables first (depend on nothing AR-level).
    op.drop_table("debit_notes")
    op.drop_table("bill_allocations")
    op.drop_table("supplier_payments")
    op.drop_table("supplier_bill_lines")
    op.drop_table("supplier_bills")

    # Drop AR tables.
    op.drop_table("credit_notes")
    op.drop_table("payment_allocations")
    op.drop_table("customer_payments")
    op.drop_table("sales_invoice_lines")
    op.drop_table("sales_invoices")
