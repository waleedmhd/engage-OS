"""Add information column to contacts for AI-agent key data reference."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "030_add_contact_information"
down_revision = "029_engagement_outreach"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("information", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("contacts", "information")
