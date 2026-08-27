"""Conv-S1 regression: POST /conversations/{id}/transition is admin-only.

Locks down two invariants of the force_transition endpoint:

  1. Non-admin callers receive 403 Forbidden (role gate).
  2. Admin callers receive an ORM User object (not a JWT dict) — the handler
     reads ``current_user.id`` and would AttributeError if the dependency
     returned the raw claims dict.

Both are exercised against the real router via the ASGI transport, with
``get_current_user_db`` patched to inject a synthetic User for each scenario.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.auth.models import User


def _user(role: str) -> User:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = role
    u.is_active = True
    return u


@pytest.mark.asyncio
async def test_force_transition_rejects_agent(app, client):
    from app.core.dependencies import get_current_user_claims, get_current_user_db

    agent = _user("agent")
    app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(agent.id), "role": "agent"}
    app.dependency_overrides[get_current_user_db] = lambda: agent
    try:
        response = await client.post(
            f"/api/v1/conversations/{uuid.uuid4()}/transition",
            json={"target_state": "closed"},
            headers={"Authorization": "Bearer fake"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user_claims, None)
        app.dependency_overrides.pop(get_current_user_db, None)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_force_transition_admin_receives_user_object(app, client):
    """The handler reads `current_user.id` — confirm the admin gate returns the
    ORM User, not the JWT claims dict (regression: AttributeError otherwise)."""
    from app.core.dependencies import (
        get_current_user_claims,
        get_current_user_db,
        get_db_session,
    )

    admin = _user("admin")
    app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(admin.id), "role": "admin"}
    app.dependency_overrides[get_current_user_db] = lambda: admin
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()

    with patch("app.modules.conversations.router.ConversationService") as MockService:
        svc = MockService.return_value
        svc.force_transition = AsyncMock(return_value=None)

        try:
            response = await client.post(
                f"/api/v1/conversations/{uuid.uuid4()}/transition",
                json={"target_state": "closed"},
                headers={"Authorization": "Bearer fake"},
            )
        finally:
            for dep in (get_current_user_claims, get_current_user_db, get_db_session):
                app.dependency_overrides.pop(dep, None)

    assert response.status_code == 204, response.text
    # service.force_transition was called with the admin's UUID (proves
    # current_user was the ORM object, not a dict)
    call = svc.force_transition.await_args
    assert call.kwargs["actor_id"] == admin.id
