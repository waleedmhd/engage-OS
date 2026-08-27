"""Drop buyer_seller_type column and constraint from contacts.

The column was never used in production — no business logic depends on it.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "023_drop_buyer_seller_type"
down_revision = "022_add_media_file_data"


def upgrade() -> None:
    op.drop_constraint(
        "ck_contacts_buyer_seller_type",
        "contacts",
        type_="check",
    )
    op.drop_column("contacts", "buyer_seller_type")


def downgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column(
            "buyer_seller_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    op.create_check_constraint(
        "ck_contacts_buyer_seller_type",
        "contacts",
        "buyer_seller_type IN ('buyer', 'seller', 'both', 'unknown')",
    )
