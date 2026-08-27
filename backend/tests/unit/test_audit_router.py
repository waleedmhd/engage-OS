"""Router-level tests for GET /audit-logs (P1.1).

The service is monkeypatched so the test isolates router + dependency
wiring; the service layer is covered by test_audit_service.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import (
    get_current_user_claims,
    get_current_user_db,
    get_db_session,
)
from app.modules.audit.schemas import AuditLogResponse
from app.schemas.common import Page


@pytest.fixture(autouse=True)
def stub_db_session(app):
    async def _fake_session():
        yield MagicMock()

    app.dependency_overrides[get_db_session] = _fake_session
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
    from app.modules.audit import router as router_module

    monkeypatch.setattr(router_module, "AuditService", lambda _session: fake)
    return fake


@pytest.mark.asyncio
async def test_audit_logs_requires_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/audit-logs")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_audit_logs_rejects_non_admin(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/audit-logs")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_audit_logs_returns_page(app, override_user, patch_service):
    override_user("admin")
    from unittest.mock import AsyncMock

    patch_service.list_logs = AsyncMock(
        return_value=Page[AuditLogResponse](
            items=[
                AuditLogResponse(
                    id=str(uuid.uuid4()),
                    actor_type="user",
                    action="update",
                    entity_type="AppSetting",
                )
            ],
            page=1,
            page_size=50,
            total=9,
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/api/v1/audit-logs?entity_type=AppSetting&action=update"
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 9
    assert len(body["items"]) == 1
    patch_service.list_logs.assert_awaited_once()
