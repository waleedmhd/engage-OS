"""Unit tests for MediaService — classify, extension_for, file handling."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.modules.media.constants import MediaType
from app.modules.media.service import MediaService


class TestMediaServiceClassify:
    def test_image(self):
        assert MediaService._classify("image/jpeg") == MediaType.IMAGE
        assert MediaService._classify("image/png") == MediaType.IMAGE
        assert MediaService._classify("image/webp") == MediaType.IMAGE

    def test_video(self):
        assert MediaService._classify("video/mp4") == MediaType.VIDEO
        assert MediaService._classify("video/quicktime") == MediaType.VIDEO

    def test_audio(self):
        assert MediaService._classify("audio/wav") == MediaType.AUDIO
        assert MediaService._classify("audio/ogg") == MediaType.AUDIO
        assert MediaService._classify("audio/webm") == MediaType.AUDIO

    def test_fallback(self):
        assert MediaService._classify("application/pdf") == MediaType.DOCUMENT
        assert MediaService._classify("application/octet-stream") == MediaType.DOCUMENT


class TestMediaServiceExtensionFor:
    def test_from_filename(self):
        assert MediaService._extension_for("photo.jpg", "image/jpeg") == ".jpg"
        assert MediaService._extension_for("video.mp4", "video/mp4") == ".mp4"
        assert MediaService._extension_for("recording.wav", "audio/wav") == ".wav"

    def test_no_extension_fallback(self):
        assert MediaService._extension_for("unnamed", "image/jpeg") == ".jpg"
        assert MediaService._extension_for("file", "image/png") == ".png"
        assert MediaService._extension_for("blob", "video/mp4") == ".mp4"
        assert MediaService._extension_for("data", "audio/mpeg") == ".mp3"
        assert MediaService._extension_for("unknown", "audio/webm") == ".webm"

    def test_unknown_mime(self):
        assert MediaService._extension_for("unnamed", "application/xyz") == ".bin"


class TestMediaServiceUpload:
    @pytest.mark.asyncio
    async def test_upload_stores_file_and_returns_asset(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.modules.media.service.MEDIA_ROOT", tmp_path
        )

        session = MagicMock()

        fake_asset = MagicMock()
        asset_id = uuid.uuid4()
        fake_asset.id = asset_id
        fake_asset.message_id = None
        fake_asset.media_type = "image"
        fake_asset.file_path = f"image/{asset_id}.jpg"
        fake_asset.mime_type = "image/jpeg"
        fake_asset.file_size_bytes = 15
        fake_asset.duration_seconds = None
        fake_asset.meta_media_id = None
        fake_asset.created_at = None

        async def fake_create(**kwargs):
            return fake_asset

        repo = MagicMock()
        repo.create = fake_create

        svc = MediaService(session)
        svc._repo = repo
        data = b"fake-image-data"
        asset = await svc.upload(
            filename="photo.jpg",
            content_type="image/jpeg",
            file_data=data,
        )

        assert asset.media_type == "image"
        assert asset.mime_type == "image/jpeg"
        assert asset.file_size_bytes == len(data)
        # The service resolves MEDIA_ROOT inside upload — check write landed.
