"""Router-level tests for assignments endpoints (Phase 5).

Covers role gating + ownership checks (agents can only lock for themselves;
admins can lock/unlock on behalf of anyone). Service layer is mocked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import (
    get_current_user_claims,
    get_current_user_db,
    get_db_session,
)


@pytest.fixture(autouse=True)
def stub_db_session(app):
    async def _fake_session():
        yield AsyncMock()
    app.dependency_overrides[get_db_session] = _fake_session
    yield
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def override_user(app):
    """Wire claims + ORM user dependency. Returns the chosen user.id."""
    user_id = uuid.uuid4()

    def _set(role: str = "agent", id_: uuid.UUID | None = None) -> uuid.UUID:
        nonlocal user_id
        if id_ is not None:
            user_id = id_
        async def _claims() -> dict:
            return {"sub": str(user_id), "role": role, "iat": 0, "exp": 9999999999}

        user = MagicMock()
        user.id = user_id
        user.role = role

        async def _user() -> object:
            return user

        app.dependency_overrides[get_current_user_claims] = _claims
        app.dependency_overrides[get_current_user_db] = _user
        return user_id

    yield _set
    app.dependency_overrides.pop(get_current_user_claims, None)
    app.dependency_overrides.pop(get_current_user_db, None)


@pytest.mark.asyncio
async def test_agent_cannot_lock_for_another_agent(app, override_user):
    """Agent A trying to lock on behalf of agent B → 403."""
    override_user("agent")
    other = uuid.uuid4()
    conv_id = uuid.uuid4()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/assignments/{conv_id}/lock",
            json={"agent_id": str(other)},
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_agent_can_lock_for_self(app, override_user, monkeypatch):
    """Happy path: agent locks for themselves → 200 + LockResponse."""
    user_id = override_user("agent")
    conv_id = uuid.uuid4()

    fake_conv = MagicMock()
    fake_conv.id = conv_id
    fake_conv.locked_by = user_id
    fake_conv.lock_expires_at = datetime.now(UTC) + timedelta(seconds=120)

    fake_service = MagicMock()
    fake_service.acquire_lock = AsyncMock(return_value=fake_conv)

    from app.modules.assignments import router as assignments_router_module
    monkeypatch.setattr(
        assignments_router_module, "AssignmentService", lambda _s: fake_service
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/assignments/{conv_id}/lock",
            json={"agent_id": str(user_id)},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == str(conv_id)
    assert body["locked_by"] == str(user_id)


@pytest.mark.asyncio
async def test_admin_can_lock_for_any_agent(app, override_user, monkeypatch):
    """Admin can lock on behalf of any agent — used for reassignment."""
    admin_id = override_user("admin")
    target_agent = uuid.uuid4()
    conv_id = uuid.uuid4()

    fake_conv = MagicMock()
    fake_conv.id = conv_id
    fake_conv.locked_by = target_agent
    fake_conv.lock_expires_at = datetime.now(UTC) + timedelta(seconds=120)

    fake_service = MagicMock()
    fake_service.acquire_lock = AsyncMock(return_value=fake_conv)

    from app.modules.assignments import router as assignments_router_module
    monkeypatch.setattr(
        assignments_router_module, "AssignmentService", lambda _s: fake_service
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/assignments/{conv_id}/lock",
            json={"agent_id": str(target_agent)},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    assert response.json()["locked_by"] == str(target_agent)


@pytest.mark.asyncio
async def test_unlock_requires_holder_or_admin(app, override_user):
    """Agent A unlocking agent B's lock without admin role → 403."""
    override_user("agent")
    other = uuid.uuid4()
    conv_id = uuid.uuid4()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/assignments/{conv_id}/unlock",
            json={"agent_id": str(other)},
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_unlock_passes_override_flag(app, override_user, monkeypatch):
    """Admin unlocking on behalf of someone else triggers admin_override=True."""
    override_user("admin")
    target_agent = uuid.uuid4()
    conv_id = uuid.uuid4()

    fake_service = MagicMock()
    fake_service.release_lock = AsyncMock(return_value=None)

    from app.modules.assignments import router as assignments_router_module
    monkeypatch.setattr(
        assignments_router_module, "AssignmentService", lambda _s: fake_service
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/assignments/{conv_id}/unlock",
            json={"agent_id": str(target_agent)},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 204
    call = fake_service.release_lock.await_args
    assert call.kwargs["admin_override"] is True
