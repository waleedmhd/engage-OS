"""ERP-0 Revision B — create ERP schemas + shared reference data.

Creates schemas `erp_fin` and `erp_inv`, plus reference tables (public schema):
currencies, fx_rates, number_sequences, uoms, documents.

Seed base currency (AED).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "erp0_b_erp_schemas"
down_revision = "erp0_a_crm_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------ currency ----
    op.create_table(
        "currencies",
        sa.Column("code", sa.String(3), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(5), nullable=False),
        sa.Column("is_base", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        "INSERT INTO currencies (code, name, symbol, is_base) VALUES "
        "('AED', 'UAE Dirham', 'د.إ', true)"
    )

    # -------------------------------------------------------------- fx_rate ----
    op.create_table(
        "fx_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("currency_code", sa.String(3), sa.ForeignKey("currencies.code"),
                  nullable=False),
        sa.Column("rate_to_aed", sa.Numeric(19, 8), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.UniqueConstraint("currency_code", "as_of_date", name="uq_fx_rates_code_date"),
    )

    # ------------------------------------------------------ number_sequence ----
    op.create_table(
        "number_sequences",
        sa.Column("doc_type", sa.String(30), primary_key=True),
        sa.Column("fiscal_year", sa.Integer(), primary_key=True),
        sa.Column("next_value", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )

    # ------------------------------------------------------------------ uom ----
    op.create_table(
        "uoms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(10), unique=True, nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
    )
    op.execute(
        "INSERT INTO uoms (id, code, name) VALUES "
        "(gen_random_uuid(), 'PCS', 'Piece'), "
        "(gen_random_uuid(), 'BOX', 'Box'), "
        "(gen_random_uuid(), 'KG', 'Kilogram')"
    )

    # ------------------------------------------------------------- documents --
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("bytes", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_documents_entity", "documents", ["entity_type", "entity_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])


def downgrade() -> None:
    op.drop_table("documents")
    op.drop_table("uoms")
    op.drop_table("number_sequences")
    op.drop_table("fx_rates")
    op.drop_table("currencies")
