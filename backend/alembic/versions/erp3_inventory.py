"""ERP-3 Revision — Inventory tables (erp_inv + crm schemas).

Creates:
  erp_inv: warehouses, locations, items, stock_units, stock_balances,
           stock_ledger_entries
  crm:     serial_nos
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "erp3_inventory"
down_revision = "erp2_ar_ap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --------------------------------------------------------- warehouses ----
    op.create_table(
        "warehouses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(20), unique=True, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.UniqueConstraint("code", name="uq_warehouses_code"),
        
    )

    # ---------------------------------------------------------- locations ----
    op.create_table(
        "locations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint(
            "warehouse_id", "code", name="uq_locations_warehouse_code"
        ),
        
    )
    op.create_index(
        "ix_locations_warehouse", "locations", ["warehouse_id"]
    )

    # --------------------------------------------------------------- items ----
    op.create_table(
        "items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("sku", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column(
            "nature",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'bulk'"),
        ),
        sa.Column(
            "uom_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uoms.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "valuation_method",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'moving_average'"),
        ),
        sa.Column("reorder_level", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "reorder_qty",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "default_purchase_price",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "default_sale_price",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "inventory_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "cogs_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "revenue_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "is_sales_item",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_purchase_item",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("end_of_life", sa.Date(), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("safety_stock", sa.Numeric(12, 2), nullable=True),
        sa.Column("weight_per_unit", sa.Numeric(10, 3), nullable=True),
        sa.Column(
            "weight_uom_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uoms.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("country_of_origin", sa.String(2), nullable=True),
        sa.Column("customs_tariff_number", sa.String(20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
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
            "nature IN ('serialized', 'bulk')",
            name="ck_items_nature",
        ),
        sa.CheckConstraint(
            "valuation_method IN ('specific_identification', 'fifo', 'moving_average')",
            name="ck_items_valuation_method",
        ),
        sa.UniqueConstraint("sku", name="uq_items_sku"),
        
    )
    op.create_index("ix_items_category", "items", ["category"])
    op.create_index("ix_items_nature", "items", ["nature"])

    # --------------------------------------------------------- stock_units ----
    op.create_table(
        "stock_units",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("serial_no", sa.String(100), unique=True, nullable=False),
        sa.Column("imei", sa.String(20), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'IN_STOCK'"),
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "purchase_cost",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "grn_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Procurement GRN reference — no FK",
        ),
        sa.Column(
            "sales_dispatch_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Fulfilment dispatch reference — no FK",
        ),
        sa.Column("warranty_expiry_date", sa.Date(), nullable=True),
        sa.Column("amc_expiry_date", sa.Date(), nullable=True),
        sa.Column("maintenance_status", sa.String(20), nullable=True),
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
            "status IN ('ON_ORDER', 'IN_STOCK', 'IN_TRANSIT', 'SOLD', 'SCRAPPED', 'RETURNED')",
            name="ck_stock_units_status",
        ),
        sa.UniqueConstraint("serial_no", name="uq_stock_units_serial_no"),
        
    )
    op.create_index(
        "ix_stock_units_serial_no", "stock_units", ["serial_no"]
    )
    op.create_index(
        "ix_stock_units_status", "stock_units", ["status"]
    )
    op.create_index(
        "ix_stock_units_item", "stock_units", ["item_id"]
    )
    op.create_index(
        "ix_stock_units_location", "stock_units", ["location_id"]
    )

    # ----------------------------------------------------- stock_balances ----
    op.create_table(
        "stock_balances",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "qty",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "avg_cost",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.UniqueConstraint(
            "item_id", "location_id", name="uq_stock_balances_item_location"
        ),
        
    )
    op.create_index(
        "ix_stock_balances_item", "stock_balances", ["item_id"]
    )
    op.create_index(
        "ix_stock_balances_location",
        "stock_balances",
        ["location_id"],
        
    )

    # ----------------------------------------------- stock_ledger_entries ----
    op.create_table(
        "stock_ledger_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "stock_unit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stock_units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("voucher_type", sa.String(30), nullable=False),
        sa.Column(
            "voucher_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "qty_change",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "valuation_rate",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "stock_value_change",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "qty_after",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_cancelled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint(
            "voucher_type IN ('grn', 'dispatch', 'transfer', 'adjustment', 'stock_count', 'opening')",
            name="ck_stock_ledger_entries_voucher_type",
        ),
        
    )
    op.create_index(
        "ix_stock_ledger_entries_item_date",
        "stock_ledger_entries",
        ["item_id", "posting_date"],
        
    )
    op.create_index(
        "ix_stock_ledger_entries_stock_unit",
        "stock_ledger_entries",
        ["stock_unit_id"],
        
    )
    op.create_index(
        "ix_stock_ledger_entries_voucher",
        "stock_ledger_entries",
        ["voucher_type", "voucher_id"],
        
    )

    # --------------------------------------------------------- serial_nos ----
    # CRM-level serial registry (Path C design).
    op.create_table(
        "serial_nos",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("serial_no", sa.String(100), unique=True, nullable=False),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("purchase_rate", sa.Numeric(19, 4), nullable=True),
        sa.Column("warranty_expiry_date", sa.Date(), nullable=True),
        sa.Column("amc_expiry_date", sa.Date(), nullable=True),
        sa.Column("maintenance_status", sa.String(20), nullable=True),
        sa.Column(
            "delivered_to",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sale_date", sa.Date(), nullable=True),
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
        sa.UniqueConstraint("serial_no", name="uq_serial_nos_serial_no"),
    )
    op.create_index(
        "ix_serial_nos_status", "serial_nos", ["status"])
    op.create_index(
        "ix_serial_nos_item", "serial_nos", ["item_id"])


def downgrade() -> None:
    op.drop_table("serial_nos")
    op.drop_table("stock_ledger_entries")
    op.drop_table("stock_balances")
    op.drop_table("stock_units")
    op.drop_table("items")
    op.drop_table("locations")
    op.drop_table("warehouses")
