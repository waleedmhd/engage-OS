"""Unit tests for SettingsService AI typed methods (mocked repo + audit)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.settings.schemas import AISettingsUpdateRequest
from app.modules.settings.service import SettingsService


@pytest.fixture
def svc():
    s = SettingsService.__new__(SettingsService)
    s.session = MagicMock()
    s.repo = MagicMock()
    s._audit = MagicMock()
    s._audit.append = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_get_ai_settings_defaults_when_unset(svc):
    svc.repo.get = AsyncMock(return_value=None)
    out = await svc.get_ai_settings()
    assert out.kill_switch is False
    assert out.auto_send_enabled is True


@pytest.mark.asyncio
async def test_get_ai_settings_reflects_stored(svc):
    async def _get(key, *, scope="global"):
        row = MagicMock()
        row.value = {"enabled": True}
        return row

    svc.repo.get = AsyncMock(side_effect=_get)
    out = await svc.get_ai_settings()
    assert out.kill_switch is True
    assert out.auto_send_enabled is True


@pytest.mark.asyncio
async def test_update_ai_settings_only_writes_provided_fields(svc):
    store: dict[str, dict] = {}
    written = []

    async def _get(key, *, scope="global"):
        if key not in store:
            return None
        row = MagicMock()
        row.value = store[key]
        return row

    async def _upsert(key, value, *, scope="global"):
        written.append((key, value))
        store[key] = value
        row = MagicMock()
        row.id = uuid.uuid4()
        row.key, row.value, row.scope = key, value, scope
        return row

    svc.repo.get = AsyncMock(side_effect=_get)
    svc.repo.upsert = AsyncMock(side_effect=_upsert)
    actor = uuid.uuid4()
    out = await svc.update_ai_settings(
        AISettingsUpdateRequest(kill_switch=True), actor_id=actor
    )
    assert written == [("ai.kill_switch", {"enabled": True})]
    assert out.kill_switch is True
    assert out.auto_send_enabled is True
    svc._audit.append.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_ai_settings_test_numbers(svc):
    store: dict[str, dict] = {}
    written = []

    async def _get(key, *, scope="global"):
        if key not in store:
            return None
        row = MagicMock()
        row.value = store[key]
        return row

    async def _upsert(key, value, *, scope="global"):
        written.append((key, value))
        store[key] = value
        row = MagicMock()
        row.id = uuid.uuid4()
        row.key, row.value, row.scope = key, value, scope
        return row

    svc.repo.get = AsyncMock(side_effect=_get)
    svc.repo.upsert = AsyncMock(side_effect=_upsert)
    actor = uuid.uuid4()
    out = await svc.update_ai_settings(
        AISettingsUpdateRequest(test_numbers=["+123", "+456"]), actor_id=actor
    )
    assert ("ai.test_numbers", {"numbers": ["+123", "+456"]}) in written
    assert out.test_numbers == ["+123", "+456"]


@pytest.mark.asyncio
async def test_resolve_test_numbers_malformed_not_list(svc):
    async def _get(key, *, scope="global"):
        row = MagicMock()
        row.value = {"numbers": "not-a-list"}
        return row

    svc.repo.get = AsyncMock(side_effect=_get)
    out = await svc.get_ai_settings()
    assert out.test_numbers == []


@pytest.mark.asyncio
async def test_update_ai_settings_test_numbers_limit(svc):
    actor = uuid.uuid4()
    with pytest.raises(ValueError, match="Maximum 5"):
        await svc.update_ai_settings(
            AISettingsUpdateRequest(test_numbers=["1", "2", "3", "4", "5", "6"]),
            actor_id=actor,
        )


# ---- _validate_business_card_media ---------------------------------------


@pytest.mark.asyncio
async def test_validate_business_card_media_invalid_uuid(svc):
    with pytest.raises(ValueError, match="Invalid UUID"):
        await svc._validate_business_card_media("not-a-uuid")


@pytest.mark.asyncio
async def test_validate_business_card_media_not_found(svc):
    svc.session.get = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="No MediaAsset found"):
        await svc._validate_business_card_media(
            "d96b2601-c59d-5f6d-8082-81a48f205365"
        )


@pytest.mark.asyncio
async def test_validate_business_card_media_no_file_data(svc):
    from app.modules.media.models import MediaAsset

    asset = MagicMock(spec=MediaAsset)
    asset.file_data = None
    svc.session.get = AsyncMock(return_value=asset)
    with pytest.raises(ValueError, match="has no stored file data"):
        await svc._validate_business_card_media(
            "d96b2601-c59d-5f6d-8082-81a48f205365"
        )


@pytest.mark.asyncio
async def test_validate_business_card_media_ok(svc):
    from app.modules.media.models import MediaAsset

    asset = MagicMock(spec=MediaAsset)
    asset.file_data = b"fake-jpeg"
    svc.session.get = AsyncMock(return_value=asset)
    # Should not raise
    await svc._validate_business_card_media(
        "d96b2601-c59d-5f6d-8082-81a48f205365"
    )
