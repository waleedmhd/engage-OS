"""Integration coverage for the Templates API (P0.2).

Seeds via the real-committing `committed_db` and drives the HTTP API with
a real JWT, exercising router → service → repository. Meta is not
configured in the test env, so submit persists a PENDING row and skips
the remote call — which is exactly what keeps the campaign approval gate
conservative.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.security import create_access_token
from tests.factories import make_user

pytestmark = pytest.mark.integration


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.mark.asyncio
async def test_submit_list_and_role_gates(committed_db, client):
    admin = make_user(committed_db, role="admin", email="tadmin@example.com")
    agent = make_user(committed_db, role="agent", email="tagent@example.com")
    committed_db.commit()

    # Admin submits — Meta not configured → PENDING, no remote id.
    resp = await client.post(
        "/api/v1/templates/submit",
        json={
            "name": "Order Update",
            "category": "utility",
            "language": "en",
            "body": "Your order {{1}} shipped.",
        },
        headers=_token(admin),
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["status"] == "pending"
    assert created["meta_template_id"] is None
    assert created["name"] == "order_update"  # normalized

    # Agent can list (agent-or-admin) and sees the row.
    listed = await client.get("/api/v1/templates", headers=_token(agent))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] >= 1
    assert any(t["name"] == "order_update" for t in body["items"])

    # Agent cannot submit (admin-only).
    forbidden = await client.post(
        "/api/v1/templates/submit",
        json={"name": "x", "category": "utility", "language": "en", "body": "y"},
        headers=_token(agent),
    )
    assert forbidden.status_code == 403

    # Duplicate name → 409.
    dupe = await client.post(
        "/api/v1/templates/submit",
        json={"name": "order_update", "category": "utility", "language": "en", "body": "z"},
        headers=_token(admin),
    )
    assert dupe.status_code == 409, dupe.text

    # Sync with no remote id → 404 (nothing to reconcile).
    tid = created["id"]
    sync = await client.post(f"/api/v1/templates/{tid}/sync", headers=_token(admin))
    assert sync.status_code == 404


@pytest.mark.asyncio
async def test_sync_unknown_template_404(committed_db, client):
    admin = make_user(committed_db, role="admin", email="tadmin2@example.com")
    committed_db.commit()
    r = await client.post(
        f"/api/v1/templates/{uuid.uuid4()}/sync", headers=_token(admin)
    )
    assert r.status_code == 404
