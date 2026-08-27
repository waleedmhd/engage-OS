"""Integration tests for manual contact tagging.

Drives router -> service -> repository against a real Postgres via
`committed_db`, with real JWTs minted via `create_access_token`. Covers the
new POST/DELETE /contacts/{id}/tags/{tag_id} endpoints, idempotency, the 404
on an unknown tag, and the resolved tag chips embedded in GET /contacts.

Follows the conventions of `test_contacts_bulk_api.py`.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.security import create_access_token
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


async def _create_tag(client, headers, name: str, color: str = "#112233") -> str:
    resp = await client.post(
        "/api/v1/categorization/tags",
        json={"name": name, "color": color},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_apply_tag_appears_in_contact_tags_and_list(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    cid = await _create_contact(client, h, "+15550700001")
    tid = await _create_tag(client, h, "VIP", "#aabbcc")

    # Apply.
    r = await client.post(f"/api/v1/categorization/contacts/{cid}/tags/{tid}", headers=h)
    assert r.status_code == 204, r.text

    # Surfaces on the contact's tag links.
    links = await client.get(f"/api/v1/categorization/contacts/{cid}/tags", headers=h)
    assert links.status_code == 200, links.text
    assert [link["tag_id"] for link in links.json()] == [tid]

    # And as a resolved chip (name + color) embedded in the contacts list.
    lst = await client.get("/api/v1/contacts?q=15550700001", headers=h)
    assert lst.status_code == 200, lst.text
    item = next(c for c in lst.json()["items"] if c["id"] == cid)
    assert len(item["tags"]) == 1
    assert item["tags"][0]["id"] == tid
    assert item["tags"][0]["name"] == "VIP"
    assert item["tags"][0]["color"] == "#aabbcc"


@pytest.mark.asyncio
async def test_apply_tag_is_idempotent(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    cid = await _create_contact(client, h, "+15550700002")
    tid = await _create_tag(client, h, "Buyer")

    r1 = await client.post(f"/api/v1/categorization/contacts/{cid}/tags/{tid}", headers=h)
    r2 = await client.post(f"/api/v1/categorization/contacts/{cid}/tags/{tid}", headers=h)
    assert r1.status_code == 204
    assert r2.status_code == 204, r2.text

    links = await client.get(f"/api/v1/categorization/contacts/{cid}/tags", headers=h)
    assert [link["tag_id"] for link in links.json()] == [tid]


@pytest.mark.asyncio
async def test_apply_unknown_tag_returns_404(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    cid = await _create_contact(client, h, "+15550700003")
    r = await client.post(
        f"/api/v1/categorization/contacts/{cid}/tags/{uuid.uuid4()}", headers=h
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_remove_tag_detaches(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    cid = await _create_contact(client, h, "+15550700004")
    tid = await _create_tag(client, h, "Cold Lead")

    await client.post(f"/api/v1/categorization/contacts/{cid}/tags/{tid}", headers=h)
    r = await client.delete(f"/api/v1/categorization/contacts/{cid}/tags/{tid}", headers=h)
    assert r.status_code == 204, r.text

    links = await client.get(f"/api/v1/categorization/contacts/{cid}/tags", headers=h)
    assert links.json() == []


@pytest.mark.asyncio
async def test_agent_can_apply_tag(committed_db, client):
    """Tagging is an agent-level action (not admin-only)."""
    admin = make_user(committed_db, role="admin")
    agent = make_user(committed_db, role="agent")
    committed_db.commit()

    cid = await _create_contact(client, _token(admin), "+15550700005")
    tid = await _create_tag(client, _token(admin), "Warm Lead")

    r = await client.post(
        f"/api/v1/categorization/contacts/{cid}/tags/{tid}", headers=_token(agent)
    )
    assert r.status_code == 204, r.text
