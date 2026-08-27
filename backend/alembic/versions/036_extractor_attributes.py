"""Phase 8 — add extracted_attributes JSONB column to market_messages.

Stores the full output of the Python MarketExtractor (Pass B + Pass C) so
the ingestion pipeline always has a record of what the extractor saw,
regardless of whether the listener path or the Python path was used.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "036_extractor_attributes"
down_revision = ("035_attribute_vocab", "035_fingerprint_dedup")
branch_labels = None
depends_on = ("035_attribute_vocab", "035_fingerprint_dedup")


def upgrade() -> None:
    op.add_column(
        "market_messages",
        sa.Column(
            "extracted_attributes",
            postgresql.JSONB,
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "COMMENT ON COLUMN market_messages.extracted_attributes IS "
            "'Precomputed Pass B+C output — source depends on MARKET_TRUST_LISTENER'"
        )
    )


def downgrade() -> None:
    op.drop_column("market_messages", "extracted_attributes")
