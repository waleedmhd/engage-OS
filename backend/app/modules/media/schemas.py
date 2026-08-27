"""Media request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MediaAssetUploadRequest(BaseModel):
    """No fields — data comes from multipart file upload."""

    pass


class MediaAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message_id: uuid.UUID | None = None
    media_type: str
    file_path: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    duration_seconds: float | None = None
    meta_media_id: str | None = None
    created_at: datetime | None = None
