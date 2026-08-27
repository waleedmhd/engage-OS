"""Add contact pipeline statuses + timestamp columns for auto-transition logic.

Adds last_contacted_at / last_inbound_at to power the contact pipeline
(active → contacted → follow_up → interested/not_interested).

Updates the ck_contacts_status_valid CHECK constraint to include the new
status values: contacted, follow_up, interested, not_interested.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "015_contact_pipeline_status"
down_revision = "014_canonicalize_contact_phone"
branch_labels = None
depends_on = None


def upgrade():
    # Add timestamp columns
    op.add_column(
        "contacts",
        sa.Column(
            "last_contacted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "last_inbound_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Create indexes
    op.create_index(
        "ix_contacts_last_contacted_at",
        "contacts",
        ["last_contacted_at"],
    )
    op.create_index(
        "ix_contacts_last_inbound_at",
        "contacts",
        ["last_inbound_at"],
    )

    # Drop old CHECK constraint and recreate with all 7 status values.
    # Alembic applies the naming convention from target_metadata to both
    # create_check_constraint and drop_constraint, so we pass the base name;
    # Alembic mangles it to ck_contacts_ck_contacts_status_valid.
    op.drop_constraint("ck_contacts_status_valid", "contacts", type_="check")
    op.create_check_constraint(
        "ck_contacts_status_valid",
        "contacts",
        sa.text(
            "status IN ("
            "'active', 'inactive', 'blocked', "
            "'contacted', 'follow_up', 'interested', 'not_interested'"
            ")"
        ),
    )


def downgrade():
    # Revert CHECK constraint to original 3 values
    op.drop_constraint("ck_contacts_status_valid", "contacts", type_="check")
    op.create_check_constraint(
        "ck_contacts_status_valid",
        "contacts",
        sa.text("status IN ('active', 'inactive', 'blocked')"),
    )

    # Drop indexes
    op.drop_index("ix_contacts_last_inbound_at", "contacts")
    op.drop_index("ix_contacts_last_contacted_at", "contacts")

    # Drop columns
    op.drop_column("contacts", "last_inbound_at")
    op.drop_column("contacts", "last_contacted_at")
