"""Add media_assets table and messages.msg_type column.

Batch 1 — Media Foundation:
  - media_assets: stores uploaded media files (image, video, audio, document)
    with type, path, MIME, size, duration, and the Meta media ID after upload.
  - messages.msg_type: discriminator column for message rendering
    ('text' | 'image' | 'video' | 'audio' | 'contact').

Both are additive only. media_assets.message_id is SET NULL on message delete,
so media files survive message removal. Existing messages default to msg_type='text'.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "016_media_assets_msg_type"
down_revision = "015_contact_pipeline_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("message_id", sa.UUID(as_uuid=True),
                  sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.Numeric(10, 2), nullable=True),
        sa.Column("meta_media_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()"), index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_check_constraint(
        "ck_media_assets_type_valid", "media_assets",
        "media_type IN ('image', 'video', 'audio', 'document')",
    )

    op.add_column(
        "messages",
        sa.Column("msg_type", sa.String(16), nullable=False, server_default="text"),
    )
    op.create_check_constraint(
        "ck_messages_msg_type_valid", "messages",
        "msg_type IN ('text', 'image', 'video', 'audio', 'contact')",
    )


def downgrade() -> None:
    op.drop_column("messages", "msg_type")
    op.drop_table("media_assets")
