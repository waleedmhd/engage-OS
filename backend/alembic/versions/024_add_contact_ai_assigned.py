"""Add ai_assigned boolean column to contacts.

When true the contact is assigned to the AI agent instead of a human.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "024_add_contact_ai_assigned"
down_revision = "023_drop_buyer_seller_type"


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column(
            "ai_assigned",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("contacts", "ai_assigned")
