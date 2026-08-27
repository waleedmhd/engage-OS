"""Media service — upload, download, conversion orchestration."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.constants import MediaType
from app.modules.media.repository import MediaAssetRepository
from app.modules.media.schemas import MediaAssetResponse

logger = structlog.get_logger(__name__)

MEDIA_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "media"


class MediaService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = MediaAssetRepository(session)

    async def upload(
        self,
        *,
        filename: str,
        content_type: str,
        file_data: bytes,
    ) -> MediaAssetResponse:
        media_type = self._classify(content_type)
        asset_id = uuid.uuid4()
        ext = self._extension_for(filename, content_type)
        rel_path = f"{media_type}/{asset_id}{ext}"
        abs_path = MEDIA_ROOT / rel_path

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(file_data)

        asset = await self._repo.create(
            id=asset_id,
            media_type=media_type.value,
            file_path=rel_path,
            mime_type=content_type,
            file_size_bytes=len(file_data),
            file_data=file_data,
        )

        logger.info(
            "media_uploaded",
            asset_id=str(asset.id),
            media_type=media_type.value,
            size_bytes=len(file_data),
        )

        return MediaAssetResponse.model_validate(asset)

    async def get_asset(self, asset_id: uuid.UUID) -> MediaAssetResponse | None:
        asset = await self._repo.get(asset_id)
        if asset is None:
            return None
        return MediaAssetResponse.model_validate(asset)

    def resolve_path(self, rel_path: str) -> Path:
        return MEDIA_ROOT / rel_path

    def convert_to_ogg(self, source_rel_path: str) -> str:
        """Convert WAV audio to Ogg/Opus for Meta. Returns relative path to .ogg."""
        src = MEDIA_ROOT / source_rel_path
        ogg_rel = source_rel_path.rsplit(".", 1)[0] + ".ogg"
        dst = MEDIA_ROOT / ogg_rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i", str(src),
                "-c:a", "libopus",
                "-b:a", "16k",
                "-ar", "16000",
                str(dst),
            ],
            capture_output=True,
            check=True,
        )

        logger.info("audio_converted", source=source_rel_path, dest=ogg_rel)
        return ogg_rel

    @staticmethod
    def _classify(content_type: str) -> MediaType:
        if content_type.startswith("image/"):
            return MediaType.IMAGE
        if content_type.startswith("video/"):
            return MediaType.VIDEO
        if content_type.startswith("audio/"):
            return MediaType.AUDIO
        return MediaType.DOCUMENT

    @staticmethod
    def _extension_for(filename: str, content_type: str) -> str:
        _, ext = os.path.splitext(filename)
        if ext:
            return ext.lower()
        # Fallback from MIME
        mime_ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "audio/wav": ".wav",
            "audio/wave": ".wav",
            "audio/ogg": ".ogg",
            "audio/opus": ".opus",
            "audio/mp3": ".mp3",
            "audio/mpeg": ".mp3",
            "audio/aac": ".aac",
            "audio/webm": ".webm",
        }
        return mime_ext.get(content_type, ".bin")
