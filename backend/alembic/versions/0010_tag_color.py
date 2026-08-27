"""Add nullable color column to tags (Settings epic piece 4).

Additive only. Existing rows stay NULL; frontend renders a default chip
color when color is null. No backfill.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "010_tag_color"
down_revision = "009_camp_recip_id_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tags",
        sa.Column("color", sa.String(length=7), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tags", "color")
