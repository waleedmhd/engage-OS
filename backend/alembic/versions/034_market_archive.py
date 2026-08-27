"""P3 market_archive table — unified raw-message archive inside the backup perimeter.

Replaces the listener's separate archive Postgres database (Decision #1).
Noise-gated messages are archived with status='noise' rather than dropped (Decision #4).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "034_market_archive"
down_revision = "033_ingest_contract_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_archive",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("group_name", sa.String(255), nullable=True),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("sender_number", sa.String(64), nullable=False),
        sa.Column(
            "message_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("message_content", sa.Text, nullable=False),
        sa.Column("msg_type", sa.String(16), nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source_msg_id", sa.String(256), unique=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="lead",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.execute(
        "ALTER TABLE market_archive ADD CONSTRAINT ck_market_archive_status_valid "
        "CHECK (status IN ('lead', 'noise', 'unreviewed'))"
    )

    op.create_index("ix_market_archive_timestamp", "market_archive", ["message_timestamp"])
    op.create_index("ix_market_archive_sender", "market_archive", ["sender_number"])
    op.create_index("ix_market_archive_status", "market_archive", ["status"])
    op.create_index("ix_market_archive_tags", "market_archive", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("market_archive")
