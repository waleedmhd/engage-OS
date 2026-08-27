"""Router-level tests for conversation endpoints — role gating.

Covers Conv-S1: force_transition is admin-only. Previously any authenticated
user could force any conversation to any state (including CLOSED), which was
an uncontrolled close-any-conversation backdoor.
"""

from __future__ import annotations

import unittest.mock
import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.dependencies import (
    get_current_user_claims,
    get_current_user_db,
    get_db_session,
)


@pytest.fixture(autouse=True)
def stub_db_session(app):
    """Override get_db_session with an AsyncMock so the role-gate tests don't
    attempt a real Postgres connection. The role gate fires before the
    handler body runs, so the session is never used."""
    async def _fake_session():
        yield AsyncMock()
    app.dependency_overrides[get_db_session] = _fake_session
    yield
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def override_user_role(app):
    """Yield a setter that swaps in claims with the given role.

    Yields the override-cleanup function so each test cleans up after itself.
    """
    def _set(role: str) -> None:
        async def _claims() -> dict:
            return {
                "sub": str(uuid.uuid4()),
                "role": role,
                "iat": 0,
                "exp": 9999999999,
            }
        app.dependency_overrides[get_current_user_claims] = _claims

    yield _set
    app.dependency_overrides.pop(get_current_user_claims, None)


@pytest.mark.asyncio
async def test_force_transition_requires_admin_role(client, override_user_role):
    """Conv-S1: a non-admin caller hitting /transition must get 403."""
    override_user_role("agent")

    conv_id = uuid.uuid4()
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/transition",
        json={"target_state": "CLOSED"},
        headers={"Authorization": "Bearer dummy"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_force_transition_admin_passes_role_gate(app, override_user_role, monkeypatch):
    """Conv-S1: an admin caller must not receive 403 from the role gate.

    The service layer is patched so the test isolates the gate. A 204 (or
    any non-403, non-500) confirms require_role("admin") accepted the
    admin claims and dispatched into the handler.
    """
    admin_id = uuid.uuid4()
    override_user_role("admin")

    mock_user = unittest.mock.MagicMock()
    mock_user.id = admin_id

    async def _admin_user() -> object:
        return mock_user

    app.dependency_overrides[get_current_user_db] = _admin_user

    # Stub out the service to avoid hitting any DB or business logic.
    async def _noop(*args, **kwargs):
        return None

    fake_service = unittest.mock.MagicMock()
    fake_service.force_transition = _noop

    from app.modules.conversations import router as conv_router_module
    monkeypatch.setattr(
        conv_router_module, "ConversationService", lambda _session: fake_service
    )

    try:
        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            conv_id = uuid.uuid4()
            response = await ac.post(
                f"/api/v1/conversations/{conv_id}/transition",
                json={"target_state": "CLOSED"},
                headers={"Authorization": "Bearer dummy"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user_db, None)

    assert response.status_code != 403, (
        f"role gate rejected admin (expected pass-through). got={response.status_code}"
    )


@pytest.mark.asyncio
async def test_non_admin_blocked_from_all_admin_endpoints(client, override_user_role):
    """Confirm 403 is returned consistently — the gate is a simple kwarg
    swap and easy to forget. Repeat the check explicitly with role=user
    to ensure the gate isn't accidentally permissive on unknown roles."""
    override_user_role("user")

    conv_id = uuid.uuid4()
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/transition",
        json={"target_state": "AI_ACTIVE"},
        headers={"Authorization": "Bearer dummy"},
    )
    assert response.status_code == 403

# ===================================================================
# Conv-M5 / P0.3 — locked_by must not leak to non-admin/non-owner.
# ===================================================================

from datetime import UTC, datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def _conv_obj(locked_by):
    return SimpleNamespace(
        id=uuid.uuid4(),
        contact_id=uuid.uuid4(),
        state="HUMAN_ASSIGNED",
        ai_enabled=True,
        locked_by=locked_by,
        lock_expires_at=datetime.now(UTC),
        last_message_at=None,
    )


async def _get_conv_as(app, monkeypatch, *, role, user_id, holder):
    async def _claims() -> dict:
        return {"sub": str(user_id), "role": role, "iat": 0, "exp": 9999999999}

    user = unittest.mock.MagicMock()
    user.id = user_id
    user.role = role

    async def _user() -> object:
        return user

    # Override session so session.get(Contact, ...) returns None — the Conv-M5
    # tests only care about locked_by masking, not contact enrichment.
    session_mock = AsyncMock()
    session_mock.get = AsyncMock(return_value=None)

    async def _session():
        yield session_mock

    app.dependency_overrides[get_current_user_claims] = _claims
    app.dependency_overrides[get_current_user_db] = _user
    app.dependency_overrides[get_db_session] = _session

    fake_service = unittest.mock.MagicMock()
    fake_service.get_conversation = AsyncMock(return_value=_conv_obj(holder))
    fake_service.mark_read = AsyncMock(return_value=None)
    from app.modules.conversations import router as conv_router_module
    monkeypatch.setattr(
        conv_router_module, "ConversationService", lambda _session: fake_service
    )
    try:
        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.get(
                f"/api/v1/conversations/{uuid.uuid4()}",
                headers={"Authorization": "Bearer dummy"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user_claims, None)
        app.dependency_overrides.pop(get_current_user_db, None)
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.asyncio
async def test_convm5_locked_by_hidden_from_non_owner_agent(app, monkeypatch):
    holder = uuid.uuid4()
    r = await _get_conv_as(
        app, monkeypatch, role="agent", user_id=uuid.uuid4(), holder=holder
    )
    assert r.status_code == 200, r.text
    assert r.json()["locked_by"] is None
    assert r.json()["lock_expires_at"] is None


@pytest.mark.asyncio
async def test_convm5_locked_by_visible_to_holder(app, monkeypatch):
    holder = uuid.uuid4()
    r = await _get_conv_as(
        app, monkeypatch, role="agent", user_id=holder, holder=holder
    )
    assert r.status_code == 200, r.text
    assert r.json()["locked_by"] == str(holder)


@pytest.mark.asyncio
async def test_convm5_locked_by_visible_to_admin(app, monkeypatch):
    holder = uuid.uuid4()
    r = await _get_conv_as(
        app, monkeypatch, role="admin", user_id=uuid.uuid4(), holder=holder
    )
    assert r.status_code == 200, r.text
    assert r.json()["locked_by"] == str(holder)
