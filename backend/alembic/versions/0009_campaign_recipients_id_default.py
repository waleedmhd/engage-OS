"""Add gen_random_uuid() server default to campaign_recipients.id.

B-12: campaign_recipients.id (UUIDPKMixin) was created without the
gen_random_uuid() server default that every other UUIDPK table has.
CampaignRecipientRepository.bulk_insert (called by validate_campaign for
audience materialisation) issues a core INSERT that does not supply id,
so every campaign validation with recipients failed in production with a
NOT NULL violation on campaign_recipients.id.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "009_camp_recip_id_default"
down_revision = "008_tag_suggestions_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "campaign_recipients",
        "id",
        server_default=sa.text("gen_random_uuid()"),
    )


def downgrade() -> None:
    op.alter_column("campaign_recipients", "id", server_default=None)
