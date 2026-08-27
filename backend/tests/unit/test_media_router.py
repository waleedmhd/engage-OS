"""Coverage fill: call media router functions directly with mocked deps."""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile


@pytest.fixture
def router_funcs():
    from app.modules.media import router as media_router
    return media_router


@pytest.mark.asyncio
async def test_upload_media_returns_201(router_funcs, monkeypatch):
    """Call upload_media directly — covers the endpoint handler."""
    import uuid as _uuid

    asset_id = _uuid.uuid4()

    class FakeAsset:
        id = asset_id
        message_id = None
        media_type = "image"
        file_path = f"image/{asset_id}.jpg"
        mime_type = "image/jpeg"
        file_size_bytes = 100
        duration_seconds = None
        meta_media_id = None
        created_at = None

    async def fake_upload(**kw):
        return FakeAsset

    session = AsyncMock()
    session.commit = AsyncMock()

    async def fake_session():
        yield session

    async def fake_user():
        u = MagicMock()
        u.id = _uuid.uuid4()
        return u

    svc_instance = MagicMock()
    svc_instance.upload = fake_upload

    monkeypatch.setattr(
        "app.modules.media.router.MediaService",
        lambda _s: svc_instance,
    )
    monkeypatch.setattr(
        "app.modules.media.router.get_db_session",
        fake_session,
    )
    monkeypatch.setattr(
        "app.modules.media.router.get_current_user_db",
        fake_user,
    )
    # Also patch MEDIA_ROOT
    import pathlib
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(
        "app.modules.media.service.MEDIA_ROOT", tmp,
    )

    file = UploadFile(filename="photo.jpg", file=io.BytesIO(b"fake"))

    from app.modules.media.router import upload_media

    resp = await upload_media(
        file=file,
        session=session,
        _user=await fake_user(),
    )

    assert resp.media_type == "image"
    assert resp.id == asset_id


@pytest.mark.asyncio
async def test_serve_media_404_for_unknown(router_funcs, monkeypatch):
    """Call serve_media directly with non-existent asset → 404."""
    import uuid as _uuid

    class FakeService:
        async def get_asset(self, _id):
            return None

    session = AsyncMock()
    async def fake_session():
        yield session

    monkeypatch.setattr(
        "app.modules.media.router.get_db_session", fake_session,
    )
    monkeypatch.setattr(
        "app.modules.media.router.MediaService", lambda _s: FakeService()
    )
    from fastapi import HTTPException

    from app.modules.media.router import serve_media

    with pytest.raises(HTTPException) as exc_info:
        await serve_media(
            asset_id=_uuid.uuid4(),
            session=session,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_serve_media_file_found_returns_file_response(router_funcs, monkeypatch):
    """Call serve_media with an existing file → returns FileResponse."""
    import pathlib
    import tempfile
    import uuid as _uuid

    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "image").mkdir()
    tmp_file = tmp / "image" / "test.jpg"
    tmp_file.write_bytes(b"fake-image")

    asset_id = _uuid.uuid4()

    class FakeAsset:
        id = asset_id
        media_type = "image"
        file_path = "image/test.jpg"
        mime_type = "image/jpeg"

    class FakeService:
        async def get_asset(self, _id):
            return FakeAsset

        def resolve_path(self, rel_path):
            return tmp / rel_path

    session = AsyncMock()
    async def fake_session():
        yield session

    monkeypatch.setattr(
        "app.modules.media.router.get_db_session", fake_session,
    )
    monkeypatch.setattr(
        "app.modules.media.router.MediaService", lambda _s: FakeService()
    )

    from app.modules.media.router import serve_media

    resp = await serve_media(
        asset_id=asset_id,
        session=session,
    )

    from fastapi.responses import FileResponse
    assert isinstance(resp, FileResponse)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_serve_media_file_missing_on_disk(router_funcs, monkeypatch):
    """Call serve_media with asset but missing file → 404."""
    import pathlib
    import tempfile
    import uuid as _uuid

    tmp = pathlib.Path(tempfile.mkdtemp())
    asset_id = _uuid.uuid4()

    class FakeAsset:
        id = asset_id
        file_path = "image/nonexistent.jpg"
        mime_type = "image/jpeg"

    class FakeService:
        async def get_asset(self, _id):
            return FakeAsset

        def resolve_path(self, rel_path):
            return tmp / rel_path

    session = AsyncMock()
    async def fake_session():
        yield session

    monkeypatch.setattr(
        "app.modules.media.router.get_db_session", fake_session,
    )
    monkeypatch.setattr(
        "app.modules.media.router.MediaService", lambda _s: FakeService()
    )

    from fastapi import HTTPException

    from app.modules.media.router import serve_media

    with pytest.raises(HTTPException) as exc_info:
        await serve_media(
            asset_id=asset_id,
            session=session,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_media_service_resolve_path():
    """MediaService.resolve_path resolves a relative path within MEDIA_ROOT."""
    import pathlib
    import tempfile

    from app.modules.media.service import MediaService

    tmp = pathlib.Path(tempfile.mkdtemp())
    svc = MediaService.__new__(MediaService)

    # Patch MEDIA_ROOT on the module level
    import app.modules.media.service as media_svc_mod

    old = media_svc_mod.MEDIA_ROOT
    media_svc_mod.MEDIA_ROOT = tmp
    try:
        p = svc.resolve_path("image/abc.jpg")
        assert p == tmp / "image/abc.jpg"
    finally:
        media_svc_mod.MEDIA_ROOT = old


@pytest.mark.asyncio
async def test_media_service_get_asset():
    """MediaService.get_asset returns None for unknown id."""
    import uuid as _uuid

    from app.modules.media.service import MediaService

    session = MagicMock()
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)

    svc = MediaService.__new__(MediaService)
    svc._session = session
    svc._repo = repo

    result = await svc.get_asset(_uuid.uuid4())
    assert result is None
    repo.get.assert_called_once()


@pytest.mark.asyncio
async def test_media_repository_get_by_message_id():
    """MediaAssetRepository.get_by_message_id executes SELECT and returns list."""
    from app.modules.media.repository import MediaAssetRepository

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    repo = MediaAssetRepository.__new__(MediaAssetRepository)
    repo.session = session

    result = await repo.get_by_message_id(uuid.uuid4())
    assert isinstance(result, list)
    assert session.execute.called


def test_media_repository_create_sync():
    """MediaAssetRepository.create_sync persists and returns a MediaAsset."""
    from app.modules.media.repository import MediaAssetRepository

    session = MagicMock()
    session.add = MagicMock()
    session.flush = MagicMock()
    session.refresh = MagicMock()

    repo = MediaAssetRepository.__new__(MediaAssetRepository)
    repo.session = session

    asset = repo.create_sync(
        id=uuid.uuid4(), message_id=None, media_type="image",
        file_path="image/x.jpg", mime_type="image/jpeg",
    )

    assert asset is not None
    session.add.assert_called_once()
    session.flush.assert_called_once()
    session.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_media_service_get_asset_found():
    """MediaService.get_asset returns the validated response when asset exists."""
    import uuid as _uuid

    from app.modules.media.service import MediaService

    asset_id = _uuid.uuid4()
    fake_asset = MagicMock()
    fake_asset.id = asset_id
    fake_asset.message_id = None
    fake_asset.media_type = "image"
    fake_asset.file_path = "image/x.jpg"
    fake_asset.mime_type = "image/jpeg"
    fake_asset.file_size_bytes = 100
    fake_asset.duration_seconds = None
    fake_asset.meta_media_id = None
    fake_asset.created_at = None

    session = MagicMock()
    repo = MagicMock()
    repo.get = AsyncMock(return_value=fake_asset)

    svc = MediaService.__new__(MediaService)
    svc._session = session
    svc._repo = repo

    result = await svc.get_asset(asset_id)
    assert result is not None
    assert result.media_type == "image"
    repo.get.assert_called_once()


def test_media_service_convert_to_ogg(monkeypatch):
    """MediaService.convert_to_ogg calls ffmpeg via subprocess."""
    import pathlib
    import tempfile

    from app.modules.media.service import MediaService

    tmp = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(
        "app.modules.media.service.MEDIA_ROOT", tmp,
    )
    # Create a dummy source file
    src = tmp / "audio" / "test.wav"
    src.parent.mkdir()
    src.write_bytes(b"fake-wav-data")

    # Mock subprocess.run to avoid needing real ffmpeg
    import subprocess
    mock_run = MagicMock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    svc = MediaService.__new__(MediaService)
    result = svc.convert_to_ogg("audio/test.wav")

    assert result == "audio/test.ogg"
    assert mock_run.called


@pytest.mark.asyncio
async def test_send_to_closed_conversation_raises():
    """send_message raises StateTransitionError for CLOSED conversations."""
    import uuid as _uuid
    from unittest.mock import AsyncMock

    from app.core.exceptions import StateTransitionError
    from app.modules.conversations.constants import ConversationState
    from app.modules.messaging.service import MessagingService

    session = AsyncMock()
    session.flush = AsyncMock()

    svc = MessagingService(session)

    closed_conv = MagicMock()
    closed_conv.id = _uuid.uuid4()
    closed_conv.state = ConversationState.CLOSED
    svc._conv_repo.get_or_404 = AsyncMock(return_value=closed_conv)

    with pytest.raises(StateTransitionError, match="CLOSED"):
        await svc.send_message(
            conversation_id=_uuid.uuid4(),
            content="test",
            actor_id=_uuid.uuid4(),
        )
