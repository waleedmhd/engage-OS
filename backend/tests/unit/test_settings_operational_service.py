"""Operational settings schemas + service (mocked repo/audit)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.modules.settings.schemas import (
    OperationalSettingsResponse,
    OperationalSettingsUpdateRequest,
)


def test_update_request_rejects_unknown_field():
    with pytest.raises(ValidationError):
        OperationalSettingsUpdateRequest(bogus=True)


def test_update_request_rejects_bad_timezone():
    with pytest.raises(ValidationError):
        OperationalSettingsUpdateRequest(timezone={"tz": "Mars/Olympus"})


def test_update_request_rejects_bad_time_format():
    with pytest.raises(ValidationError):
        OperationalSettingsUpdateRequest(
            business_hours={"enabled": True, "start": "9am", "end": "18:00"}
        )


def test_update_request_rejects_end_not_after_start():
    with pytest.raises(ValidationError):
        OperationalSettingsUpdateRequest(
            business_hours={"enabled": True, "start": "18:00", "end": "09:00"}
        )


def test_update_request_rejects_non_positive_limit():
    with pytest.raises(ValidationError):
        OperationalSettingsUpdateRequest(
            campaign_daily_cap={"enabled": True, "limit": 0}
        )


def test_update_request_accepts_partial_valid():
    req = OperationalSettingsUpdateRequest(read_only_mode={"enabled": True})
    assert req.read_only_mode.enabled is True
    assert req.timezone is None


def _service_with_mocks():
    from app.modules.settings.service import SettingsService

    svc = SettingsService.__new__(SettingsService)
    svc.session = AsyncMock()
    svc.repo = MagicMock()
    svc._audit = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_get_operational_returns_defaults_when_unset():
    svc = _service_with_mocks()
    svc.repo.get = AsyncMock(return_value=None)
    resp = await svc.get_operational_settings()
    assert isinstance(resp, OperationalSettingsResponse)
    assert resp.read_only_mode.enabled is False
    assert resp.timezone.tz == "UTC"
    assert resp.campaign_daily_cap.limit == 800
    assert resp.campaign_daily_cap.enabled is True
    assert resp.business_hours.enabled is False


@pytest.mark.asyncio
async def test_get_operational_merges_stored_values():
    svc = _service_with_mocks()

    async def _get(key, *, scope="global"):
        if key == "ops.timezone":
            row = MagicMock()
            row.value = {"tz": "Europe/London"}
            return row
        return None

    svc.repo.get = AsyncMock(side_effect=_get)
    resp = await svc.get_operational_settings()
    assert resp.timezone.tz == "Europe/London"
    assert resp.read_only_mode.enabled is False


@pytest.mark.asyncio
async def test_update_operational_only_sets_provided_groups():
    svc = _service_with_mocks()
    svc.repo.get = AsyncMock(return_value=None)
    svc.set_setting = AsyncMock()
    actor = uuid.uuid4()

    req = OperationalSettingsUpdateRequest(read_only_mode={"enabled": True})
    await svc.update_operational_settings(req, actor_id=actor)

    svc.set_setting.assert_awaited_once()
    args, kwargs = svc.set_setting.await_args
    assert args[0] == "ops.read_only_mode"
    assert args[1] == {"enabled": True}
    assert kwargs["actor_id"] == actor
