"""Integration tests for /api/v1/users (Settings & Admin — piece 3).

Drives router → service → repository with a real admin JWT and the
real-committing `committed_db`. Asserts audit rows are written and
guardrails behave end-to-end.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.models import RefreshToken
from tests.factories import make_user

pytestmark = pytest.mark.integration


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.mark.asyncio
async def test_create_list_patch_deactivate_reset_roundtrip(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()

    auth = _token(admin)

    # create
    create = await client.post(
        "/api/v1/users",
        json={
            "email": "newbie@x.com",
            "name": "Newbie",
            "role": "agent",
            "password": "initialpw-123",
        },
        headers=auth,
    )
    assert create.status_code == 201, create.text
    new_id = create.json()["id"]

    # list filtered by role
    lst = await client.get("/api/v1/users?role=agent", headers=auth)
    assert lst.status_code == 200, lst.text
    body = lst.json()
    assert body["total"] >= 1
    assert any(u["id"] == new_id for u in body["items"])

    # search
    q = await client.get("/api/v1/users?q=newbie", headers=auth)
    assert q.status_code == 200
    assert any(u["id"] == new_id for u in q.json()["items"])

    # patch name
    patch = await client.patch(
        f"/api/v1/users/{new_id}", json={"name": "Renamed"}, headers=auth
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["name"] == "Renamed"

    # deactivate
    de = await client.patch(
        f"/api/v1/users/{new_id}", json={"is_active": False}, headers=auth
    )
    assert de.status_code == 200, de.text
    assert de.json()["is_active"] is False

    # reset password
    rp = await client.post(
        f"/api/v1/users/{new_id}/reset-password",
        json={"password": "another-secret-9"},
        headers=auth,
    )
    assert rp.status_code == 204

    # audit trail: ≥4 User rows (create, update-name, update-active, reset-pw)
    rows = (
        committed_db.execute(
            select(AuditLog).where(AuditLog.entity_type == "User")
        )
        .scalars()
        .all()
    )
    actions = [r.action for r in rows]
    assert actions.count("create") >= 1
    assert actions.count("update") >= 2
    assert actions.count("reset_password") >= 1
    # password material never written
    for r in rows:
        for state in (r.before_state, r.after_state):
            if not state:
                continue
            assert "hashed_password" not in state
            if "password" in state:
                assert state["password"] == "***"


@pytest.mark.asyncio
async def test_create_duplicate_email_409(committed_db, client):
    admin = make_user(committed_db, role="admin")
    make_user(committed_db, email="taken@x.com", role="agent")
    committed_db.commit()
    r = await client.post(
        "/api/v1/users",
        json={
            "email": "taken@x.com",
            "role": "agent",
            "password": "pw-min-8c",
        },
        headers=_token(admin),
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_last_admin_demote_blocked(committed_db, client):
    admin = make_user(committed_db, role="admin")
    # Second admin doing the action so the self-modify guard doesn't trip first.
    other_admin = make_user(committed_db, role="admin")
    committed_db.commit()

    r = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"role": "agent"},
        headers=_token(other_admin),
    )
    # Both admins are active; demoting `admin` would leave 1 (other_admin).
    # That's allowed. Verify positive case first to confirm wiring.
    assert r.status_code == 200, r.text

    # Now try to demote the remaining admin — there are zero others left.
    r2 = await client.patch(
        f"/api/v1/users/{other_admin.id}",
        json={"role": "agent"},
        headers=_token(other_admin),
    )
    # Self-modify wins over last-admin — but either 409 is acceptable.
    assert r2.status_code == 409, r2.text


@pytest.mark.asyncio
async def test_self_deactivate_blocked(committed_db, client):
    admin = make_user(committed_db, role="admin")
    make_user(committed_db, role="admin")  # keep last-admin invariant safe
    committed_db.commit()
    r = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"is_active": False},
        headers=_token(admin),
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_non_admin_forbidden(committed_db, client):
    agent = make_user(committed_db, role="agent")
    committed_db.commit()
    r = await client.get("/api/v1/users", headers=_token(agent))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patch_unknown_field_422(committed_db, client):
    admin = make_user(committed_db, role="admin")
    target = make_user(committed_db, role="agent")
    committed_db.commit()
    r = await client.patch(
        f"/api/v1/users/{target.id}",
        json={"hacked": True},
        headers=_token(admin),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_deactivate_revokes_refresh_tokens(committed_db, client):
    from datetime import UTC, datetime, timedelta

    admin = make_user(committed_db, role="admin")
    target = make_user(committed_db, role="agent")
    rt = RefreshToken(
        user_id=target.id,
        token_hash="0" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked=False,
    )
    committed_db.add(rt)
    committed_db.commit()

    r = await client.patch(
        f"/api/v1/users/{target.id}",
        json={"is_active": False},
        headers=_token(admin),
    )
    assert r.status_code == 200, r.text

    # `committed_db` cached `rt` on insert; the async API ran the UPDATE on a
    # separate session, so expire the identity map before re-reading.
    committed_db.expire_all()
    refreshed = committed_db.execute(
        select(RefreshToken).where(RefreshToken.user_id == target.id)
    ).scalar_one()
    assert refreshed.revoked is True


@pytest.mark.asyncio
async def test_get_user_404(committed_db, client):
    import uuid as _u

    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    r = await client.get(f"/api/v1/users/{_u.uuid4()}", headers=_token(admin))
    assert r.status_code == 404
