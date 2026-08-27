"""Router tests for the typed /settings/ai endpoints (service mocked)."""

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
from app.modules.settings.schemas import AISettingsResponse


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
async def test_ai_get_rejects_non_admin(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/settings/ai")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_ai_get_returns_block(app, override_user, patch_service):
    override_user("admin")
    patch_service.get_ai_settings = AsyncMock(
        return_value=AISettingsResponse(
            kill_switch=False,
            auto_send_enabled=True,
            test_numbers=[],
            tag_suggestions_enabled=True,
            response_generation_enabled=True,
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/settings/ai")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "kill_switch": False,
        "auto_send_enabled": True,
        "test_numbers": [],
        "tag_suggestions_enabled": True,
        "response_generation_enabled": True,
        "business_card_media_id": None,
    }


@pytest.mark.asyncio
async def test_ai_put_unknown_field_422(app, override_user, patch_service):
    override_user("admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put("/api/v1/settings/ai", json={"bogus": True})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_ai_put_commits_and_returns(app, override_user, patch_service):
    override_user("admin")
    patch_service.update_ai_settings = AsyncMock(
        return_value=AISettingsResponse(
            kill_switch=True,
            auto_send_enabled=True,
            test_numbers=[],
            tag_suggestions_enabled=True,
            response_generation_enabled=True,
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put("/api/v1/settings/ai", json={"kill_switch": True})
    assert r.status_code == 200, r.text
    assert r.json()["kill_switch"] is True
    patch_service.update_ai_settings.assert_awaited_once()
    app.state._test_session.commit.assert_awaited_once()
