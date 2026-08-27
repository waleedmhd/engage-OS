"""Router-level tests for the Settings endpoints (P1.2).

Service is monkeypatched; service layer covered by test_settings_service.py.
"""

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
from app.modules.settings.schemas import SettingResponse


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
async def test_settings_requires_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/settings")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_settings_rejects_non_admin(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/settings")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_and_get(app, override_user, patch_service):
    override_user("admin")
    patch_service.list_settings = AsyncMock(
        return_value=[SettingResponse(key="k", value={"rate": 10}, scope="global")]
    )
    patch_service.get_setting = AsyncMock(
        return_value=SettingResponse(key="k", value={"rate": 10})
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        lst = await ac.get("/api/v1/settings")
        one = await ac.get("/api/v1/settings/k")
    assert lst.status_code == 200
    assert lst.json()[0]["key"] == "k"
    assert one.status_code == 200
    assert one.json()["value"] == {"rate": 10}


@pytest.mark.asyncio
async def test_put_commits_and_returns(app, override_user, patch_service):
    override_user("admin")
    patch_service.set_setting = AsyncMock(
        return_value=SettingResponse(key="k", value={"rate": 25})
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put("/api/v1/settings/k", json={"value": {"rate": 25}})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == {"rate": 25}
    patch_service.set_setting.assert_awaited_once()
    app.state._test_session.commit.assert_awaited_once()
