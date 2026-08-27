"""Integration tests for POST /contacts/bulk-update and /contacts/bulk-delete.

Drives router -> service -> repository against a real Postgres via
`committed_db`, with real JWTs minted via `create_access_token`.
Follows the conventions of `test_users_api.py` and `test_audit_api.py`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from tests.factories import make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


async def _create_contact(client, headers, phone: str, name: str = "C") -> str:
    resp = await client.post(
        "/api/v1/contacts",
        json={"phone": phone, "name": name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ============================================================ bulk-update


@pytest.mark.asyncio
async def test_bulk_update_admin_happy_path(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    ids = [
        await _create_contact(client, h, "+15550000001"),
        await _create_contact(client, h, "+15550000002"),
        await _create_contact(client, h, "+15550000003"),
    ]

    resp = await client.post(
        "/api/v1/contacts/bulk-update",
        json={"ids": ids, "patch": {"status": "inactive"}},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 3
    assert body["failed"] == []


@pytest.mark.asyncio
async def test_bulk_update_partial_failure(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    real_ids = [
        await _create_contact(client, h, "+15550000011"),
        await _create_contact(client, h, "+15550000012"),
    ]
    ghost = str(uuid.uuid4())

    resp = await client.post(
        "/api/v1/contacts/bulk-update",
        json={"ids": [*real_ids, ghost], "patch": {"status": "inactive"}},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == ghost
    assert body["failed"][0]["error"] == "not_found"


@pytest.mark.asyncio
async def test_bulk_update_agent_can_patch_status(committed_db, client):
    agent = make_user(committed_db, role="agent")
    committed_db.commit()
    h = _token(agent)

    ids = [
        await _create_contact(client, h, "+15550000021"),
        await _create_contact(client, h, "+15550000022"),
    ]

    resp = await client.post(
        "/api/v1/contacts/bulk-update",
        json={"ids": ids, "patch": {"status": "inactive"}},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    assert body["failed"] == []


@pytest.mark.asyncio
async def test_bulk_update_agent_assigned_agent_id_forbidden(committed_db, client):
    agent = make_user(committed_db, role="agent")
    other = make_user(committed_db, role="agent")
    committed_db.commit()
    h = _token(agent)

    cid = await _create_contact(client, h, "+15550000031")

    resp = await client.post(
        "/api/v1/contacts/bulk-update",
        json={
            "ids": [cid],
            "patch": {"assigned_agent_id": str(other.id)},
        },
        headers=h,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "bulk_assign_admin_only"


@pytest.mark.asyncio
async def test_bulk_update_empty_patch_rejected(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    cid = await _create_contact(client, h, "+15550000041")

    resp = await client.post(
        "/api/v1/contacts/bulk-update",
        json={"ids": [cid], "patch": {}},
        headers=h,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_bulk_update_over_cap_rejected(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    too_many = [str(uuid.uuid4()) for _ in range(101)]
    resp = await client.post(
        "/api/v1/contacts/bulk-update",
        json={"ids": too_many, "patch": {"status": "inactive"}},
        headers=h,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_bulk_update_emits_single_audit_row(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    ids = [
        await _create_contact(client, h, "+15550000051"),
        await _create_contact(client, h, "+15550000052"),
    ]

    resp = await client.post(
        "/api/v1/contacts/bulk-update",
        json={"ids": ids, "patch": {"status": "inactive"}},
        headers=h,
    )
    assert resp.status_code == 200, resp.text

    rows = (
        committed_db.execute(
            select(AuditLog).where(AuditLog.action == "contact.bulk_updated")
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    after = rows[0].after_state
    assert after["count"] == 2
    assert after["failed_count"] == 0
    assert set(after["target_ids"]) == set(ids)
    assert after["patch"] == {"status": "inactive"}


# ============================================================ bulk-delete


@pytest.mark.asyncio
async def test_bulk_delete_admin_happy_path(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    ids = [
        await _create_contact(client, h, "+15550000101"),
        await _create_contact(client, h, "+15550000102"),
        await _create_contact(client, h, "+15550000103"),
    ]

    resp = await client.post(
        "/api/v1/contacts/bulk-delete",
        json={"ids": ids},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 3
    assert body["failed"] == []

    for cid in ids:
        g = await client.get(f"/api/v1/contacts/{cid}", headers=h)
        assert g.status_code == 404, g.text


@pytest.mark.asyncio
async def test_bulk_delete_agent_forbidden(committed_db, client):
    admin = make_user(committed_db, role="admin")
    agent = make_user(committed_db, role="agent")
    committed_db.commit()
    admin_h = _token(admin)
    agent_h = _token(agent)

    cid = await _create_contact(client, admin_h, "+15550000111")

    resp = await client.post(
        "/api/v1/contacts/bulk-delete",
        json={"ids": [cid]},
        headers=agent_h,
    )
    assert resp.status_code == 403, resp.text
