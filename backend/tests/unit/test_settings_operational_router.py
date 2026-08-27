"""Router tests for /settings/operational (service mocked)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import (
    get_current_user_claims,
    get_current_user_db,
    get_db_session,
)
from app.modules.settings.schemas import OperationalSettingsResponse

_RESP = OperationalSettingsResponse(
    read_only_mode={"enabled": False},
    timezone={"tz": "Asia/Dubai"},
    business_hours={"enabled": False, "start": "09:00", "end": "18:00"},
    campaign_daily_cap={"enabled": True, "limit": 800},
    delivery_failure_retry={"enabled": True},
)


@pytest.fixture(autouse=True)
def stub_db_session(app):
    session = AsyncMock()
    session.commit = AsyncMock()

    async def _fake_session():
        yield session

    app.dependency_overrides[get_db_session] = _fake_session
    app.state._test_session = session
    yield
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def override_user(app):
    def _set(role: str = "admin") -> None:
        uid = uuid.uuid4()

        async def _claims() -> dict:
            return {"sub": str(uid), "role": role, "iat": 0, "exp": 9999999999}

        user = MagicMock()
        user.id = uid
        user.role = role

        async def _user() -> object:
            return user

        app.dependency_overrides[get_current_user_claims] = _claims
        app.dependency_overrides[get_current_user_db] = _user

    yield _set
    app.dependency_overrides.pop(get_current_user_claims, None)
    app.dependency_overrides.pop(get_current_user_db, None)


@pytest.fixture
def patch_service(monkeypatch):
    fake = MagicMock()
    from app.modules.settings import router as router_module

    monkeypatch.setattr(router_module, "SettingsService", lambda _s: fake)
    return fake


@pytest.mark.asyncio
async def test_operational_get_rejects_non_admin(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/settings/operational")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_operational_get_returns_block(app, override_user, patch_service):
    override_user("admin")
    patch_service.get_operational_settings = AsyncMock(return_value=_RESP)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/settings/operational")
    assert r.status_code == 200, r.text
    assert r.json()["timezone"]["tz"] == "Asia/Dubai"


@pytest.mark.asyncio
async def test_operational_put_unknown_field_422(app, override_user, patch_service):
    override_user("admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put("/api/v1/settings/operational", json={"bogus": 1})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_operational_put_commits(app, override_user, patch_service):
    override_user("admin")
    patch_service.update_operational_settings = AsyncMock(return_value=_RESP)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put(
            "/api/v1/settings/operational",
            json={"read_only_mode": {"enabled": True}},
        )
    assert r.status_code == 200, r.text
    patch_service.update_operational_settings.assert_awaited_once()
    app.state._test_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_operational_resolves_before_key_catchall(
    app, override_user, patch_service
):
    """`/settings/operational` must hit the typed handler, not GET /{key}."""
    override_user("admin")
    patch_service.get_operational_settings = AsyncMock(return_value=_RESP)
    patch_service.get_setting = AsyncMock(
        side_effect=AssertionError("catch-all /{key} was hit")
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/settings/operational")
    assert r.status_code == 200
    patch_service.get_operational_settings.assert_awaited_once()
