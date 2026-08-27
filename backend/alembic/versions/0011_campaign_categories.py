"""Add campaign_categories taxonomy + Campaign.category_id FK (Settings epic piece 5).

Additive only. The fixed CampaignType StrEnum stays untouched; this is a
display-only taxonomy admins manage from /settings/campaign-categories.
Delete is blocked at the service layer by a 409; the ondelete=RESTRICT FK
is defense in depth.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "011_campaign_categories"
down_revision = "010_tag_color"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", name="uq_campaign_categories_name"),
    )
    op.create_index(
        "ix_campaign_categories_name", "campaign_categories", ["name"], unique=False
    )

    op.add_column(
        "campaigns",
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_campaigns_category_id",
        "campaigns",
        "campaign_categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_campaigns_category_id", "campaigns", ["category_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_campaigns_category_id", table_name="campaigns")
    op.drop_constraint("fk_campaigns_category_id", "campaigns", type_="foreignkey")
    op.drop_column("campaigns", "category_id")
    op.drop_index("ix_campaign_categories_name", table_name="campaign_categories")
    op.drop_table("campaign_categories")
