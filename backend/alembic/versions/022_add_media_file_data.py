"""Add file_data column to media_assets for worker resiliency.

Media files are uploaded via the API container but sent by the worker
container. Without a shared volume, the worker cannot read files written
by the API. Storing the bytes in the DB lets the worker reconstruct the
file on its own filesystem when the shared volume is absent.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "022_add_media_file_data"
down_revision = "021_add_delivery_retry_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_assets",
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("media_assets", "file_data")
