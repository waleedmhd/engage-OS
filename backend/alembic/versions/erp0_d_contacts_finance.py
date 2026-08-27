"""ERP-0 Revision D — extend contacts table for finance.

Path C design: financial columns go directly on contacts (no separate
customer_profile table). A contact is financeable if credit_limit IS NOT NULL.

Also widens revenue_attributed / estimated_ltv to NUMERIC(19,4) for consistency
with all other ERP monetary columns (previously NUMERIC(14,2)).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "erp0_d_contacts_finance"
down_revision = "erp0_c_audit_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widen monetary columns to match ERP standard NUMERIC(19,4).
    op.alter_column(
        "contacts", "revenue_attributed",
        type_=sa.Numeric(19, 4), existing_type=sa.Numeric(14, 2),
        existing_nullable=False, server_default=sa.text("0"),
    )
    op.alter_column(
        "contacts", "estimated_ltv",
        type_=sa.Numeric(19, 4), existing_type=sa.Numeric(14, 2),
        existing_nullable=True,
    )

    # Financial columns — nullable means "not a finance contact yet."
    op.add_column("contacts", sa.Column(
        "credit_limit", sa.Numeric(19, 4), nullable=True,
    ))
    op.add_column("contacts", sa.Column(
        "payment_terms", sa.String(50), nullable=True,
    ))
    op.add_column("contacts", sa.Column(
        "ar_account_id", postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column("contacts", sa.Column(
        "ap_account_id", postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column("contacts", sa.Column(
        "default_currency_code", sa.String(3),
        sa.ForeignKey("currencies.code", ondelete="SET NULL"),
        nullable=True,
    ))
    op.add_column("contacts", sa.Column(
        "opening_balance", sa.Numeric(19, 4), nullable=True,
    ))
    op.add_column("contacts", sa.Column(
        "tax_id", sa.String(50), nullable=True,
    ))

    op.create_index(
        "ix_contacts_credit_limit", "contacts", ["credit_limit"],
        postgresql_where=sa.text("credit_limit IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_contacts_credit_limit", table_name="contacts",
                  postgresql_where=sa.text("credit_limit IS NOT NULL"))
    op.drop_column("contacts", "tax_id")
    op.drop_column("contacts", "opening_balance")
    op.drop_column("contacts", "default_currency_code")
    op.drop_column("contacts", "ap_account_id")
    op.drop_column("contacts", "ar_account_id")
    op.drop_column("contacts", "payment_terms")
    op.drop_column("contacts", "credit_limit")
    op.alter_column(
        "contacts", "estimated_ltv",
        type_=sa.Numeric(14, 2), existing_type=sa.Numeric(19, 4),
        existing_nullable=True,
    )
    op.alter_column(
        "contacts", "revenue_attributed",
        type_=sa.Numeric(14, 2), existing_type=sa.Numeric(19, 4),
        existing_nullable=False, server_default=sa.text("0"),
    )
