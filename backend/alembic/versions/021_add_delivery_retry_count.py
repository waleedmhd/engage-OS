"""Add delivery_retry_count to messages for delivery-failure retry tracking.

Separate from retry_count (which counts send-attempt retries for Meta API
errors). This column counts how many times a delivery-status webhook reported
"failed" and the system re-queued the message for re-send.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "021_add_delivery_retry_count"
down_revision = "020_add_error_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "delivery_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "delivery_retry_count")
