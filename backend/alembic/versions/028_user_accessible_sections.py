"""Add user_accessible_sections table for per-user sidebar section visibility.

Admin is an implicit wildcard (no rows needed). Agents get explicit grants;
if an agent has zero grants they default to CRM-only sections.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "028_user_accessible_sections"
down_revision = "erp4_procurement_fulfilment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_accessible_sections",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "section_key",
            sa.String(100),
            nullable=False,
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_user_accessible_sections_user",
        "user_accessible_sections",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("user_accessible_sections")
