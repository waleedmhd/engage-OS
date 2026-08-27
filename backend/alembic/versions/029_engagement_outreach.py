"""Engagement outreach lifecycle — do_not_contact, outreach_state columns, and
auto-apply tags (agent-engagement-policy §2, §5, §6).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "029_engagement_outreach"
down_revision = "seed_business_card_media"
branch_labels = None
depends_on = None

# Engagement policy §6 auto-applied tags (system-derived, no approval needed).
_NEW_TAGS = (
    "NEEDS_FOLLOW_UP",
    "UNRESPONSIVE",
    "UNDELIVERABLE",
    "INVALID_NUMBER",
    "NOT_ON_WHATSAPP",
    "DO_NOT_CONTACT",
)


def upgrade() -> None:
    # --- contacts: do_not_contact flag (§2 opt-out override) ---
    op.add_column(
        "contacts",
        sa.Column(
            "do_not_contact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_contacts_do_not_contact",
        "contacts",
        ["do_not_contact"],
    )

    # --- conversations: outreach_state (§5 lifecycle tracking) ---
    op.add_column(
        "conversations",
        sa.Column(
            "outreach_state",
            sa.String(32),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_conversations_outreach_state",
        "conversations",
        ["outreach_state"],
    )

    # --- campaign_recipients: outreach_state (cold track §4.1) ---
    op.add_column(
        "campaign_recipients",
        sa.Column(
            "outreach_state",
            sa.String(32),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_campaign_recipients_outreach_state",
        "campaign_recipients",
        ["outreach_state"],
    )

    # --- tags: insert the 6 auto-apply tags (idempotent ON CONFLICT) ---
    stmt = sa.text(
        """
        INSERT INTO tags (name) VALUES (:name)
        ON CONFLICT (name) DO NOTHING
        """
    )
    for tag_name in _NEW_TAGS:
        op.execute(stmt.bindparams(name=tag_name))


def downgrade() -> None:
    op.drop_index("ix_campaign_recipients_outreach_state", table_name="campaign_recipients")
    op.drop_column("campaign_recipients", "outreach_state")

    op.drop_index("ix_conversations_outreach_state", table_name="conversations")
    op.drop_column("conversations", "outreach_state")

    op.drop_index("ix_contacts_do_not_contact", table_name="contacts")
    op.drop_column("contacts", "do_not_contact")

    # Tags are intentionally NOT removed in the downgrade — they may already be
    # referenced by contact_tags rows created after the migration ran.
