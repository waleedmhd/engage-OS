"""Unit tests for SettingsService — repo + audit AsyncMocked (P1.2)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.modules.settings.service import SettingsService


def _make_service():
    svc = SettingsService(AsyncMock())
    svc.repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


def _row(key="campaign.global_rate_per_second", value=None, scope="global"):
    return SimpleNamespace(
        id=uuid.uuid4(), key=key, value=value or {"rate": 10}, scope=scope
    )


@pytest.mark.asyncio
async def test_list_settings_maps_rows():
    svc = _make_service()
    svc.repo.list_all.return_value = [_row(), _row(key="x", value={"a": 1})]
    out = await svc.list_settings()
    assert len(out) == 2
    assert out[0].value == {"rate": 10}
    assert out[1].key == "x"


@pytest.mark.asyncio
async def test_get_setting_not_found_raises():
    svc = _make_service()
    svc.repo.get.return_value = None
    with pytest.raises(NotFoundError):
        await svc.get_setting("missing")


@pytest.mark.asyncio
async def test_get_setting_returns_row():
    svc = _make_service()
    svc.repo.get.return_value = _row(key="test.key", value={"v": 1})
    out = await svc.get_setting("test.key")
    assert out.key == "test.key"
    assert out.value == {"v": 1}


@pytest.mark.asyncio
async def test_set_setting_audits_before_and_after():
    svc = _make_service()
    actor = uuid.uuid4()
    svc.repo.get.return_value = _row(value={"rate": 5})
    svc.repo.upsert.return_value = _row(value={"rate": 25})

    out = await svc.set_setting(
        "campaign.global_rate_per_second", {"rate": 25}, actor_id=actor
    )

    assert out.value == {"rate": 25}
    svc.repo.upsert.assert_awaited_once_with(
        "campaign.global_rate_per_second", {"rate": 25}, scope="global"
    )
    _, kwargs = svc._audit.append.call_args
    assert kwargs["entity_type"] == "AppSetting"
    assert kwargs["action"] == "update"
    assert kwargs["actor_id"] == actor
    assert kwargs["before_state"] == {"value": {"rate": 5}}
    assert kwargs["after_state"]["value"] == {"rate": 25}


@pytest.mark.asyncio
async def test_set_setting_before_state_none_when_new():
    svc = _make_service()
    svc.repo.get.return_value = None
    svc.repo.upsert.return_value = _row(key="new.key", value={"v": 1})

    await svc.set_setting("new.key", {"v": 1})

    _, kwargs = svc._audit.append.call_args
    assert kwargs["before_state"] is None
