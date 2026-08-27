"""Add client_memories table for per-contact AI memory files on the Railway volume.

Each row tracks a JSON memory file at /app/media/memories/{contact_id}.json.
The file is the source of truth; the DB row is an index for lookups and metadata.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "025_client_memories"
down_revision = "024_add_contact_ai_assigned"


def upgrade() -> None:
    op.create_table(
        "client_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column(
            "version",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("summary_preview", sa.Text, nullable=True),
        sa.Column(
            "total_interactions",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_memories")),
        sa.UniqueConstraint("contact_id", name=op.f("uq_client_memories_contact_id")),
    )
    op.create_index(
        op.f("ix_client_memories_contact_id"),
        "client_memories",
        ["contact_id"],
    )


def downgrade() -> None:
    op.drop_table("client_memories")
