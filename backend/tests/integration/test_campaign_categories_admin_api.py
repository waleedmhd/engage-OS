"""Integration tests for admin CampaignCategory CRUD endpoints (Settings epic piece 5).

Mirrors tests/integration/test_tags_admin_api.py: real admin JWT,
committed_db, audit assertions, 409 in-use semantics end-to-end.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.modules.audit.constants import AuditAction
from app.modules.audit.models import AuditLog
from app.modules.campaigns.models import CampaignCategory
from tests.factories import make_campaign, make_template, make_user

pytestmark = pytest.mark.integration


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.mark.asyncio
async def test_create_update_delete_round_trip(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    name = f"promo-{uuid.uuid4().hex[:6]}"
    r = await client.post(
        "/api/v1/campaign-categories",
        json={"name": name, "color": "#ff0000"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    category_id = body["id"]
    assert body["name"] == name
    assert body["color"] == "#ff0000"

    r2 = await client.patch(
        f"/api/v1/campaign-categories/{category_id}",
        json={"color": "#00ff00"},
        headers=auth,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["color"] == "#00ff00"

    r3 = await client.delete(
        f"/api/v1/campaign-categories/{category_id}", headers=auth
    )
    assert r3.status_code == 204

    rows = (
        committed_db.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "campaign_category")
            .where(AuditLog.entity_id == uuid.UUID(category_id))
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
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    r = await client.post(
        "/api/v1/campaign-categories",
        json={"name": f"persist-{uuid.uuid4().hex[:6]}", "color": "#abcdef"},
        headers=auth,
    )
    assert r.status_code == 201
    cid = uuid.UUID(r.json()["id"])

    row = committed_db.execute(
        select(CampaignCategory).where(CampaignCategory.id == cid)
    ).scalar_one()
    assert row.color == "#abcdef"


@pytest.mark.asyncio
async def test_agent_cannot_create_or_delete(committed_db, client):
    admin = make_user(committed_db, role="admin")
    agent = make_user(committed_db, role="agent")
    committed_db.commit()

    create = await client.post(
        "/api/v1/campaign-categories",
        json={"name": f"x-{uuid.uuid4().hex[:6]}"},
        headers=_token(admin),
    )
    assert create.status_code == 201
    category_id = create.json()["id"]

    bad = await client.post(
        "/api/v1/campaign-categories",
        json={"name": "agent-cannot"},
        headers=_token(agent),
    )
    assert bad.status_code == 403

    bad_del = await client.delete(
        f"/api/v1/campaign-categories/{category_id}", headers=_token(agent)
    )
    assert bad_del.status_code == 403


@pytest.mark.asyncio
async def test_delete_blocked_when_used_by_campaign(committed_db, client):
    admin = make_user(committed_db, role="admin")
    template = make_template(committed_db)
    committed_db.commit()
    auth = _token(admin)

    r = await client.post(
        "/api/v1/campaign-categories",
        json={"name": f"used-{uuid.uuid4().hex[:6]}"},
        headers=auth,
    )
    cid = uuid.UUID(r.json()["id"])

    campaign = make_campaign(committed_db, template=template)
    campaign.category_id = cid
    committed_db.commit()

    deny = await client.delete(
        f"/api/v1/campaign-categories/{cid}", headers=auth
    )
    assert deny.status_code == 409
    body = deny.json()
    assert "campaigns" in str(body) or "campaign_category_in_use" in str(body)


@pytest.mark.asyncio
async def test_pagination_and_search_returns_envelope(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    base = f"pg-{uuid.uuid4().hex[:6]}"
    for i in range(3):
        r = await client.post(
            "/api/v1/campaign-categories",
            json={"name": f"{base}-{i}"},
            headers=auth,
        )
        assert r.status_code == 201

    p1 = await client.get(
        f"/api/v1/campaign-categories?q={base}&limit=2&offset=0", headers=auth
    )
    assert p1.status_code == 200
    body1 = p1.json()
    assert body1["total"] == 3
    assert len(body1["items"]) == 2
    assert body1["limit"] == 2
    assert body1["offset"] == 0
    assert all(it["usage_count"] == 0 for it in body1["items"])


@pytest.mark.asyncio
async def test_create_duplicate_name_returns_409(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    name = f"dup-{uuid.uuid4().hex[:6]}"
    r1 = await client.post(
        "/api/v1/campaign-categories", json={"name": name}, headers=auth
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/campaign-categories", json={"name": name}, headers=auth
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_update_color_validation_422(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    r = await client.post(
        "/api/v1/campaign-categories",
        json={"name": f"val-{uuid.uuid4().hex[:6]}"},
        headers=auth,
    )
    cid = r.json()["id"]

    bad = await client.patch(
        f"/api/v1/campaign-categories/{cid}",
        json={"color": "not-hex"},
        headers=auth,
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_campaign_create_accepts_category_id_round_trip(committed_db, client):
    admin = make_user(committed_db, role="admin")
    template = make_template(committed_db)
    committed_db.commit()
    auth = _token(admin)

    r = await client.post(
        "/api/v1/campaign-categories",
        json={"name": f"cat-{uuid.uuid4().hex[:6]}"},
        headers=auth,
    )
    cid = r.json()["id"]

    create = await client.post(
        "/api/v1/campaigns",
        json={
            "template_id": str(template.id),
            "name": "Hello",
            "category_id": cid,
        },
        headers=auth,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["category_id"] == cid


@pytest.mark.asyncio
async def test_campaign_create_rejects_unknown_category_id(committed_db, client):
    admin = make_user(committed_db, role="admin")
    template = make_template(committed_db)
    committed_db.commit()
    auth = _token(admin)

    bogus = str(uuid.uuid4())
    create = await client.post(
        "/api/v1/campaigns",
        json={
            "template_id": str(template.id),
            "name": "Hello",
            "category_id": bogus,
        },
        headers=auth,
    )
    assert create.status_code == 404
