"""P0 groundwork — new enums, config, review_status column, AppSetting seeds.

Adds MIXED to market_messages.side, human to product_aliases.source,
review_status column + constraint, and two market confidence AppSetting rows.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "032_p0_groundwork"
down_revision = "031_market_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop existing enum-check constraints, re-add with new values.
    #    Use raw SQL to bypass Alembic's naming-convention auto-prefix (the
    #    base.py NAMING_CONVENTION template "ck_%(table_name)s_%(constraint_name)s"
    #    would otherwise double-prefix constraint names, causing a mismatch with
    #    the names created by migration 031's op.create_table).
    #    market_messages.side: add MIXED
    op.execute("ALTER TABLE market_messages DROP CONSTRAINT IF EXISTS ck_market_messages_side_valid")
    op.execute(
        "ALTER TABLE market_messages ADD CONSTRAINT ck_market_messages_side_valid "
        "CHECK (side IN ('BUY', 'SELL', 'MIXED', 'UNKNOWN'))"
    )

    #    product_aliases.source: add human
    op.execute("ALTER TABLE product_aliases DROP CONSTRAINT IF EXISTS ck_product_aliases_source_valid")
    op.execute(
        "ALTER TABLE product_aliases ADD CONSTRAINT ck_product_aliases_source_valid "
        "CHECK (source IN ('seed', 'llm_learned', 'human'))"
    )

    # 2. Add review_status column to market_messages.
    op.add_column(
        "market_messages",
        sa.Column(
            "review_status",
            sa.String(24),
            nullable=False,
            server_default="AUTO",
            index=True,
        ),
    )
    op.execute(
        "ALTER TABLE market_messages ADD CONSTRAINT ck_market_messages_review_status_valid "
        "CHECK (review_status IN ('AUTO', 'PENDING', 'REVIEWED', 'DISMISSED', 'UNREVIEWED_EXPIRED'))"
    )
    # Index for the urgent-review-queue query: PENDING items ordered by expires_at.
    op.create_index(
        "ix_market_messages_review_status_expires",
        "market_messages",
        ["review_status", "expires_at"],
    )

    # 3. Seed AppSetting rows for market confidence thresholds.
    app_settings = sa.table(
        "app_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.dialects.postgresql.JSONB),
        sa.column("scope", sa.String),
    )
    op.bulk_insert(app_settings, [
        {"key": "market.confidence.auto_min", "value": {"value": 0.85}, "scope": "global"},
        {"key": "market.confidence.review_min", "value": {"value": 0.55}, "scope": "global"},
    ])


def downgrade() -> None:
    # Remove AppSetting rows.
    op.execute("DELETE FROM app_settings WHERE key IN ('market.confidence.auto_min', 'market.confidence.review_min')")

    # Drop the review_status column and constraint.
    op.execute("ALTER TABLE market_messages DROP CONSTRAINT IF EXISTS ck_market_messages_review_status_valid")
    op.drop_index("ix_market_messages_review_status_expires", table_name="market_messages")
    op.drop_column("market_messages", "review_status")

    # Revert product_aliases.source to original values.
    op.execute("ALTER TABLE product_aliases DROP CONSTRAINT IF EXISTS ck_product_aliases_source_valid")
    op.execute(
        "ALTER TABLE product_aliases ADD CONSTRAINT ck_product_aliases_source_valid "
        "CHECK (source IN ('seed', 'llm_learned'))"
    )

    # Revert market_messages.side to original values.
    op.execute("ALTER TABLE market_messages DROP CONSTRAINT IF EXISTS ck_market_messages_side_valid")
    op.execute(
        "ALTER TABLE market_messages ADD CONSTRAINT ck_market_messages_side_valid "
        "CHECK (side IN ('BUY', 'SELL', 'UNKNOWN'))"
    )
