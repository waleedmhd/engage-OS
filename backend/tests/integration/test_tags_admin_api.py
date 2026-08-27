"""Integration tests for admin Tag CRUD endpoints (Settings epic piece 4).

Pattern follows tests/integration/test_users_api.py: real admin JWT,
committed_db, asserts audit rows + 409 in-use semantics end-to-end.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.modules.audit.constants import AuditAction
from app.modules.audit.models import AuditLog
from app.modules.categorization.constants import TagSuggestionStatus
from app.modules.categorization.models import ContactTag, Tag, TagSuggestion
from tests.factories import make_contact, make_user

pytestmark = pytest.mark.integration


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.mark.asyncio
async def test_create_update_delete_round_trip(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    name = f"vip-{uuid.uuid4().hex[:6]}"
    r = await client.post(
        "/api/v1/categorization/tags",
        json={"name": name, "color": "#ff0000"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    tag_id = body["id"]
    assert body["name"] == name
    assert body["color"] == "#ff0000"

    r2 = await client.patch(
        f"/api/v1/categorization/tags/{tag_id}",
        json={"color": "#00ff00"},
        headers=auth,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["color"] == "#00ff00"

    r3 = await client.delete(f"/api/v1/categorization/tags/{tag_id}", headers=auth)
    assert r3.status_code == 204

    # Audit trail recorded all three actions against entity_type="tag".
    rows = (
        committed_db.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "tag")
            .where(AuditLog.entity_id == uuid.UUID(tag_id))
            .order_by(AuditLog.created_at.asc())
        )
        .scalars()
        .all()
    )
    actions = [r.action for r in rows]
    assert AuditAction.CREATE.value in actions
    assert AuditAction.UPDATE.value in actions
    assert AuditAction.DELETE.value in actions


@pytest.mark.asyncio
async def test_create_persists_color_through_commit(committed_db, client):
    """Round-trip equivalent of the previously-planned service-tier test."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    r = await client.post(
        "/api/v1/categorization/tags",
        json={"name": f"persist-{uuid.uuid4().hex[:6]}", "color": "#abcdef"},
        headers=auth,
    )
    assert r.status_code == 201
    tag_id = uuid.UUID(r.json()["id"])

    # Read directly from the DB (bypassing the API) — verifies the migration
    # added the column and the row was actually committed.
    row = committed_db.execute(
        select(Tag).where(Tag.id == tag_id)
    ).scalar_one()
    assert row.color == "#abcdef"


@pytest.mark.asyncio
async def test_agent_cannot_create_or_delete(committed_db, client):
    admin = make_user(committed_db, role="admin")
    agent = make_user(committed_db, role="agent")
    committed_db.commit()

    create = await client.post(
        "/api/v1/categorization/tags",
        json={"name": f"hot-{uuid.uuid4().hex[:6]}"},
        headers=_token(admin),
    )
    assert create.status_code == 201
    tag_id = create.json()["id"]

    bad = await client.post(
        "/api/v1/categorization/tags",
        json={"name": "agent-cannot"},
        headers=_token(agent),
    )
    assert bad.status_code == 403

    bad_del = await client.delete(
        f"/api/v1/categorization/tags/{tag_id}", headers=_token(agent)
    )
    assert bad_del.status_code == 403


@pytest.mark.asyncio
async def test_delete_blocked_when_in_use_by_contact(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    r = await client.post(
        "/api/v1/categorization/tags",
        json={"name": f"used-{uuid.uuid4().hex[:6]}"},
        headers=auth,
    )
    tag_id = uuid.UUID(r.json()["id"])

    contact = make_contact(committed_db)
    committed_db.add(ContactTag(contact_id=contact.id, tag_id=tag_id))
    committed_db.commit()

    deny = await client.delete(f"/api/v1/categorization/tags/{tag_id}", headers=auth)
    assert deny.status_code == 409
    body = deny.json()
    # Counts surface in details via the global exception handler.
    flat = str(body)
    assert "contacts" in flat or "tag_in_use" in flat


@pytest.mark.asyncio
async def test_delete_blocked_when_pending_suggestion_exists(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    r = await client.post(
        "/api/v1/categorization/tags",
        json={"name": f"sug-{uuid.uuid4().hex[:6]}"},
        headers=auth,
    )
    tag_id = uuid.UUID(r.json()["id"])

    contact = make_contact(committed_db)
    committed_db.add(
        TagSuggestion(
            id=uuid.uuid4(),
            contact_id=contact.id,
            tag_id=tag_id,
            status=TagSuggestionStatus.PENDING.value,
        )
    )
    committed_db.commit()

    deny = await client.delete(f"/api/v1/categorization/tags/{tag_id}", headers=auth)
    assert deny.status_code == 409


@pytest.mark.asyncio
async def test_pagination_and_search_returns_envelope(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    base = f"pg-{uuid.uuid4().hex[:6]}"
    for i in range(3):
        r = await client.post(
            "/api/v1/categorization/tags",
            json={"name": f"{base}-{i}"},
            headers=auth,
        )
        assert r.status_code == 201

    p1 = await client.get(
        f"/api/v1/categorization/tags?q={base}&limit=2&offset=0", headers=auth
    )
    assert p1.status_code == 200
    body1 = p1.json()
    assert body1["total"] == 3
    assert len(body1["items"]) == 2
    assert body1["limit"] == 2
    assert body1["offset"] == 0
    # usage_count present and zero on freshly-created tags
    assert all(it["usage_count"] == 0 for it in body1["items"])

    p2 = await client.get(
        f"/api/v1/categorization/tags?q={base}&limit=2&offset=2", headers=auth
    )
    body2 = p2.json()
    assert len(body2["items"]) == 1


@pytest.mark.asyncio
async def test_usage_count_reflects_contact_links(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    name = f"cnt-{uuid.uuid4().hex[:6]}"
    r = await client.post("/api/v1/categorization/tags", json={"name": name}, headers=auth)
    tag_id = uuid.UUID(r.json()["id"])

    contact = make_contact(committed_db)
    committed_db.add(ContactTag(contact_id=contact.id, tag_id=tag_id))
    committed_db.commit()

    lst = await client.get(f"/api/v1/categorization/tags?q={name}", headers=auth)
    assert lst.status_code == 200
    items = lst.json()["items"]
    assert len(items) == 1
    assert items[0]["usage_count"] == 1


@pytest.mark.asyncio
async def test_create_duplicate_name_returns_409(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    name = f"dup-{uuid.uuid4().hex[:6]}"
    r1 = await client.post("/api/v1/categorization/tags", json={"name": name}, headers=auth)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/categorization/tags", json={"name": name}, headers=auth)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_update_color_validation_400(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    r = await client.post(
        "/api/v1/categorization/tags",
        json={"name": f"val-{uuid.uuid4().hex[:6]}"},
        headers=auth,
    )
    tag_id = r.json()["id"]

    bad = await client.patch(
        f"/api/v1/categorization/tags/{tag_id}",
        json={"color": "not-hex"},
        headers=auth,
    )
    assert bad.status_code == 422
