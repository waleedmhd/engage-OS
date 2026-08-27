"""Seed the persona business card MediaAsset + setting (data-only migration).

Idempotent — skips if either row already exists. The JPEG file must be
present on the Railway volume at /app/media/image/Sara_business_card.jpeg
(relative to MEDIA_ROOT). The file contents are read and stored as file_data
so the Celery worker can reconstruct the file from DB bytes regardless of
shared-volume availability.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "seed_business_card_media"
down_revision = "028_user_accessible_sections"
branch_labels = None
depends_on = None

# Deterministic UUID — idempotent across repeated runs.
_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_ASSET_ID = uuid.uuid5(_NAMESPACE, "Sara_business_card.jpeg")
_FILE_PATH = "image/Sara_business_card.jpeg"

# MEDIA_ROOT relative to the backend directory (same as media/service.py).
_MEDIA_ROOT = Path(__file__).resolve().parent.parent.parent / "media"


def _read_file_data() -> bytes | None:
    """Read the business card JPEG from the shared volume if present."""
    src = _MEDIA_ROOT / _FILE_PATH
    if not src.exists():
        return None
    return src.read_bytes()


def upgrade() -> None:
    conn = op.get_bind()

    file_data = _read_file_data()
    file_size = len(file_data) if file_data else 0

    # --- MediaAsset row ---
    existing = conn.execute(
        sa.text("SELECT 1 FROM media_assets WHERE id = :id"),
        {"id": _ASSET_ID},
    ).scalar()
    if not existing:
        conn.execute(
            sa.text(
                """
                INSERT INTO media_assets
                    (id, media_type, file_path, mime_type, file_size_bytes, file_data)
                VALUES
                    (:id, 'image', :file_path, 'image/jpeg', :file_size_bytes, :file_data)
                """
            ),
            {
                "id": _ASSET_ID,
                "file_path": _FILE_PATH,
                "file_size_bytes": file_size,
                "file_data": file_data,
            },
        )
    else:
        # Existing row: backfill file_data if it's NULL (fix for pre-022 seeds).
        row = conn.execute(
            sa.text(
                "SELECT file_data FROM media_assets WHERE id = :id"
            ),
            {"id": _ASSET_ID},
        ).first()
        if row is not None and row[0] is None and file_data:
            conn.execute(
                sa.text(
                    "UPDATE media_assets SET file_data = :file_data, "
                    "file_size_bytes = :file_size_bytes WHERE id = :id"
                ),
                {
                    "id": _ASSET_ID,
                    "file_data": file_data,
                    "file_size_bytes": file_size,
                },
            )

    # --- Setting row ---
    setting_value = '{"media_asset_id": "' + str(_ASSET_ID) + '"}'
    conn.execute(
        sa.text(
            """
            INSERT INTO app_settings (key, value, scope)
            VALUES ('ai.business_card_media_id', CAST(:value AS jsonb), 'global')
            ON CONFLICT (scope, key) DO UPDATE SET value = EXCLUDED.value
            """
        ),
        {"value": setting_value},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM app_settings "
            "WHERE key = 'ai.business_card_media_id' AND scope = 'global'"
        )
    )
    conn.execute(
        sa.text("DELETE FROM media_assets WHERE id = :id"),
        {"id": _ASSET_ID},
    )
