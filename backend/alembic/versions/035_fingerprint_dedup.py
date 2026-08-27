"""P10 fingerprint dedup — seen_count + source_groups on market_messages.

Fingerprint = sha256(sender_raw | side | sorted(product_ids) | storage).
Redis SET NX with MARKET_FINGERPRINT_WINDOW_HOURS TTL gates re-posts.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "035_fingerprint_dedup"
down_revision = "034_market_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_messages",
        sa.Column(
            "seen_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "market_messages",
        sa.Column(
            "source_groups",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("market_messages", "source_groups")
    op.drop_column("market_messages", "seen_count")
