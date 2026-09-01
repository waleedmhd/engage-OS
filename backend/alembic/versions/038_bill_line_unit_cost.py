"""Rename supplier_bill_lines.unit_price to unit_cost.

erp2_ar_ap created the column as ``unit_price``, but the model
(``payables.models.SupplierBillLine``), the schema (``BillLineRequest``) and
``BillService.create`` have always written ``unit_cost``. Every attempt to
create a supplier bill therefore failed with UndefinedColumnError, so the
table has never held a row and the rename cannot lose data.

The model name wins: it is what three layers of code already agree on, and
``unit_cost`` is also the term used by the GRN and PO line tables.

Revision ID: 038_bill_line_unit_cost
Revises: 037_market_search_tsv
"""

from alembic import op

revision = "038_bill_line_unit_cost"
down_revision = "037_market_search_tsv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded so the migration is a no-op on any database that already
    # matches the model (e.g. one built from metadata rather than migrations).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'supplier_bill_lines' AND column_name = 'unit_price'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'supplier_bill_lines' AND column_name = 'unit_cost'
            ) THEN
                ALTER TABLE supplier_bill_lines RENAME COLUMN unit_price TO unit_cost;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'supplier_bill_lines' AND column_name = 'unit_cost'
            ) THEN
                ALTER TABLE supplier_bill_lines RENAME COLUMN unit_cost TO unit_price;
            END IF;
        END $$;
        """
    )
