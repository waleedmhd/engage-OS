"""P1 ingest contract v2 — group metadata, per-line side, precomputed trust path.

Adds group_name/sender_name/msg_type to market_messages,
side to market_message_products (unused until P8, schema lands early).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "033_ingest_contract_v2"
down_revision = "032_p0_groundwork"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. market_messages — capture metadata from the listener.
    op.add_column(
        "market_messages",
        sa.Column("group_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "market_messages",
        sa.Column("sender_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "market_messages",
        sa.Column("msg_type", sa.String(16), nullable=True),
    )

    # 2. market_message_products — per-line side (P8 populates; schema lands
    #    early so P8 is code-only).
    op.add_column(
        "market_message_products",
        sa.Column("side", sa.String(8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_message_products", "side")
    op.drop_column("market_messages", "msg_type")
    op.drop_column("market_messages", "sender_name")
    op.drop_column("market_messages", "group_name")
