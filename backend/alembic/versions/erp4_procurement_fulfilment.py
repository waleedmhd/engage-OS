"""ERP-4 Revision — Procurement and Fulfilment tables (erp_inv schema).

Creates:
  erp_inv: purchase_orders, purchase_order_lines, goods_receipt_notes, grn_lines,
           sales_orders, sales_order_lines, dispatches, dispatch_lines
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "erp4_procurement_fulfilment"
down_revision = "erp3_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----------------------------------------------------- purchase_orders ----
    op.create_table(
        "purchase_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("po_no", sa.String(30), unique=True, nullable=False),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "currency_code",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'AED'"),
        ),
        sa.Column(
            "status",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'received', 'closed', 'cancelled')",
            name="ck_purchase_orders_status",
        ),
        sa.UniqueConstraint("po_no", name="uq_purchase_orders_po_no"),
        
    )
    op.create_index(
        "ix_purchase_orders_supplier",
        "purchase_orders",
        ["supplier_id"],
        
    )
    op.create_index(
        "ix_purchase_orders_status",
        "purchase_orders",
        ["status"],
        
    )

    # ------------------------------------------------- purchase_order_lines ----
    op.create_table(
        "purchase_order_lines",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "po_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "description",
            sa.String(500),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "qty",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unit_cost",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "line_total",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        
    )
    op.create_index(
        "ix_purchase_order_lines_po",
        "purchase_order_lines",
        ["po_id"],
        
    )

    # ------------------------------------------------- goods_receipt_notes ----
    op.create_table(
        "goods_receipt_notes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("grn_no", sa.String(30), unique=True, nullable=False),
        sa.Column(
            "po_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "je_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'cancelled')",
            name="ck_goods_receipt_notes_status",
        ),
        sa.UniqueConstraint("grn_no", name="uq_goods_receipt_notes_grn_no"),
        
    )
    op.create_index(
        "ix_goods_receipt_notes_po",
        "goods_receipt_notes",
        ["po_id"],
        
    )
    op.create_index(
        "ix_goods_receipt_notes_warehouse",
        "goods_receipt_notes",
        ["warehouse_id"],
        
    )

    # ------------------------------------------------------------ grn_lines ----
    op.create_table(
        "grn_lines",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "grn_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("goods_receipt_notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("serial_no", sa.String(100), nullable=True),
        sa.Column("imei", sa.String(20), nullable=True),
        sa.Column(
            "qty_received",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unit_cost",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "line_total",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        
    )
    op.create_index(
        "ix_grn_lines_grn",
        "grn_lines",
        ["grn_id"],
        
    )
    op.create_index(
        "ix_grn_lines_serial_no",
        "grn_lines",
        ["serial_no"],
        
    )

    # --------------------------------------------------------- sales_orders ----
    op.create_table(
        "sales_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("so_no", sa.String(30), unique=True, nullable=False),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "currency_code",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'AED'"),
        ),
        sa.Column(
            "status",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'dispatched', 'invoiced', 'cancelled')",
            name="ck_sales_orders_status",
        ),
        sa.UniqueConstraint("so_no", name="uq_sales_orders_so_no"),
        
    )
    op.create_index(
        "ix_sales_orders_customer",
        "sales_orders",
        ["customer_id"],
        
    )
    op.create_index(
        "ix_sales_orders_status",
        "sales_orders",
        ["status"],
        
    )

    # ----------------------------------------------------- sales_order_lines ----
    op.create_table(
        "sales_order_lines",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "so_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sales_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "description",
            sa.String(500),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "qty",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unit_price",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "line_total",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        
    )
    op.create_index(
        "ix_sales_order_lines_so",
        "sales_order_lines",
        ["so_id"],
        
    )

    # ------------------------------------------------------------ dispatches ----
    op.create_table(
        "dispatches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dispatch_no", sa.String(30), unique=True, nullable=False),
        sa.Column(
            "so_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sales_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dispatch_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "je_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'cancelled')",
            name="ck_dispatches_status",
        ),
        sa.UniqueConstraint("dispatch_no", name="uq_dispatches_dispatch_no"),
        
    )
    op.create_index(
        "ix_dispatches_so",
        "dispatches",
        ["so_id"],
        
    )

    # ------------------------------------------------------- dispatch_lines ----
    op.create_table(
        "dispatch_lines",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dispatch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dispatches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stock_unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stock_units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "qty",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unit_cost",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        
    )
    op.create_index(
        "ix_dispatch_lines_dispatch",
        "dispatch_lines",
        ["dispatch_id"],
        
    )


def downgrade() -> None:
    op.drop_table("dispatch_lines")
    op.drop_table("dispatches")
    op.drop_table("sales_order_lines")
    op.drop_table("sales_orders")
    op.drop_table("grn_lines")
    op.drop_table("goods_receipt_notes")
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
