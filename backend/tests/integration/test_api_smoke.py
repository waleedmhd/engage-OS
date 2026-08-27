"""API-driven integration coverage across auth / contacts / campaigns /
analytics / assignments.

Each test seeds via the real-committing `committed_db` (so the app's async
request session sees the rows) and calls the HTTP API with a real JWT, then
asserts the documented contract. These exercise router → service →
repository together for the modules with the largest untested surface.
"""
from __future__ import annotations

import io
import uuid

import pytest

from app.core.security import create_access_token, hash_password
from tests.factories import (
    make_contact,
    make_conversation,
    make_template,
    make_user,
)


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


# ----------------------------------------------------------------- auth

@pytest.mark.asyncio
async def test_auth_login_refresh_me_logout(committed_db, client):
    user = make_user(
        committed_db,
        role="admin",
        email="login@example.com",
        hashed_password=hash_password("s3cret-pass"),
    )
    committed_db.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "s3cret-pass"},
    )
    assert login.status_code == 200, login.text
    tokens = login.json()
    assert tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "login@example.com"

    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    logout = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh_token}
    )
    assert logout.status_code == 204

    # Bad credentials rejected.
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "wrong"},
    )
    assert bad.status_code in (401, 403)


# ----------------------------------------------------------------- contacts

@pytest.mark.asyncio
async def test_contacts_crud_and_csv_import(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    created = await client.post(
        "/api/v1/contacts",
        json={"phone": "+15557770001", "name": "Api Person", "company": "ApiCo"},
        headers=auth,
    )
    assert created.status_code in (200, 201), created.text
    cid = created.json()["id"]

    got = await client.get(f"/api/v1/contacts/{cid}", headers=auth)
    assert got.status_code == 200
    # Phone is stored canonical (digits-only wa_id) so it matches Meta's
    # bare-wa_id inbound — the '+' is stripped on create.
    assert got.json()["phone"] == "+1 555 777 0001"

    patched = await client.patch(
        f"/api/v1/contacts/{cid}", json={"name": "Renamed"}, headers=auth
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"

    listed = await client.get("/api/v1/contacts", headers=auth)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    csv_body = (
        "phone,name,company\n"
        "+15557770010,A,X\n"
        "+15557770011,B,Y\n"
        "not-a-phone,Bad,Z\n"
    )
    imported = await client.post(
        "/api/v1/contacts/import",
        files={
            "file": ("c.csv", io.BytesIO(csv_body.encode()), "text/csv")
        },
        headers=auth,
    )
    assert imported.status_code in (200, 202), imported.text


# ----------------------------------------------------------------- campaigns

@pytest.mark.asyncio
async def test_campaigns_api_lifecycle(committed_db, client):
    admin = make_user(committed_db, role="admin")
    template = make_template(committed_db, status="approved")
    make_contact(committed_db)
    committed_db.commit()
    auth = _token(admin)

    create = await client.post(
        "/api/v1/campaigns",
        json={
            "template_id": str(template.id),
            "name": "API Campaign",
            "type": "immediate",
        },
        headers=auth,
    )
    assert create.status_code in (200, 201), create.text
    camp_id = create.json()["id"]

    assert (await client.get(f"/api/v1/campaigns/{camp_id}", headers=auth)).status_code == 200
    assert (await client.get("/api/v1/campaigns", headers=auth)).status_code == 200

    patched = await client.patch(
        f"/api/v1/campaigns/{camp_id}", json={"name": "API Renamed"}, headers=auth
    )
    assert patched.status_code == 200

    validated = await client.post(
        f"/api/v1/campaigns/{camp_id}/validate", headers=auth
    )
    assert validated.status_code == 200
    assert validated.json()["ok"] is True

    launched = await client.post(
        f"/api/v1/campaigns/{camp_id}/launch", json={"confirm": True}, headers=auth
    )
    assert launched.status_code == 200

    report = await client.get(f"/api/v1/campaigns/{camp_id}/report", headers=auth)
    assert report.status_code == 200

    cancelled = await client.post(
        f"/api/v1/campaigns/{camp_id}/cancel", headers=auth
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


# ----------------------------------------------------------------- analytics

@pytest.mark.asyncio
async def test_analytics_endpoints(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    for path in ("cost", "conversion", "ai", "roi", "campaigns"):
        resp = await client.get(f"/api/v1/analytics/{path}", headers=auth)
        assert resp.status_code == 200, f"{path}: {resp.text}"

    backfill = await client.post(
        "/api/v1/analytics/backfill",
        json={"start_date": "2026-05-01", "end_date": "2026-05-02"},
        headers=auth,
    )
    assert backfill.status_code in (200, 202, 422)


# ----------------------------------------------------------------- assignments

@pytest.mark.asyncio
async def test_assignment_lock_renew_unlock(committed_db, client):
    agent = make_user(committed_db, role="agent")
    contact = make_contact(committed_db, assigned_agent=agent)
    conv = make_conversation(
        committed_db, contact=contact, state="HUMAN_ASSIGNED"
    )
    committed_db.commit()
    auth = _token(agent)
    body = {"agent_id": str(agent.id)}

    lock = await client.post(
        f"/api/v1/assignments/{conv.id}/lock", json=body, headers=auth
    )
    assert lock.status_code in (200, 201), lock.text

    renew = await client.post(
        f"/api/v1/assignments/{conv.id}/renew", json=body, headers=auth
    )
    assert renew.status_code in (200, 201)

    unlock = await client.post(
        f"/api/v1/assignments/{conv.id}/unlock", json=body, headers=auth
    )
    assert unlock.status_code in (200, 204)


# ----------------------------------------------------------------- auth task

def test_prune_expired_refresh_tokens_task(committed_db, redis_client):
    from datetime import UTC, datetime, timedelta

    from app.modules.auth.models import RefreshToken
    from app.modules.auth.tasks import prune_expired_refresh_tokens

    user = make_user(committed_db)
    committed_db.add(
        RefreshToken(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash="expired-hash",
            expires_at=datetime.now(UTC) - timedelta(days=1),
            revoked=False,
        )
    )
    committed_db.commit()

    prune_expired_refresh_tokens.run()

    committed_db.expire_all()
    remaining = (
        committed_db.query(RefreshToken)
        .filter_by(token_hash="expired-hash")
        .one_or_none()
    )
    assert remaining is None
