"""Phase 7 — attribute_vocab table: closed facets + open seed lists from listener constants.js.

Seeds region, activation, condition, logistics, currency, variant, risk, trust
(closed), plus color and brand (open). Canonical labels and aliases are
extracted from the regex patterns in the listener's filter/constants.js.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "035_attribute_vocab"
down_revision = "034_market_archive"
branch_labels = None
depends_on = None


def _seed_table() -> sa.Table:
    return sa.table(
        "attribute_vocab",
        sa.column("category", sa.String(32)),
        sa.column("kind", sa.String(64)),
        sa.column("tag", sa.String(128)),
        sa.column("canonical", sa.String(255)),
        sa.column("aliases", postgresql.JSONB),
        sa.column("is_active", sa.Boolean),
    )


def _rows_from_entries(entries):
    return [
        {
            "category": cat,
            "kind": kind,
            "tag": tag,
            "canonical": canonical,
            "aliases": aliases,
            "is_active": True,
        }
        for cat, kind, tag, canonical, aliases in entries
    ]


def upgrade() -> None:
    from app.modules.market.vocab_seed import SEED_BRAND, SEED_CLOSED, SEED_COLOR

    op.create_table(
        "attribute_vocab",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("tag", sa.String(128), nullable=False),
        sa.Column("canonical", sa.String(255), nullable=False),
        sa.Column(
            "aliases",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("category", "tag"),
    )
    op.create_index("idx_av_category", "attribute_vocab", ["category"])
    op.create_index("idx_av_kind", "attribute_vocab", ["kind"])

    tbl = _seed_table()

    op.bulk_insert(tbl, _rows_from_entries(SEED_CLOSED))
    op.bulk_insert(tbl, _rows_from_entries(SEED_COLOR))
    op.bulk_insert(tbl, _rows_from_entries(SEED_BRAND))


def downgrade() -> None:
    op.drop_table("attribute_vocab")
