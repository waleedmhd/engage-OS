"""Integration tests for the inbox tag filter + per-row tag chips.

Seeds contacts/conversations/tags via the sync committed_db session and
factories, then asserts through GET /api/v1/conversations (router -> repository
-> real Postgres). Mirrors test_contact_tags_api.py / test_lock_expiry_reaper.py
conventions.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.security import create_access_token
from app.modules.categorization.models import ContactTag, Tag
from tests.factories import make_contact, make_conversation, make_user

pytestmark = pytest.mark.integration


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


def _make_tag(session, name: str, color: str) -> Tag:
    t = Tag(id=uuid.uuid4(), name=name, color=color)
    session.add(t)
    session.flush()
    return t


def _apply_tag(session, contact, tag) -> None:
    session.add(ContactTag(contact_id=contact.id, tag_id=tag.id))
    session.flush()


@pytest.mark.asyncio
async def test_filter_returns_only_tagged_conversations(committed_db, client):
    admin = make_user(committed_db, role="admin")
    contact_a = make_contact(committed_db, phone="+15550800001")
    contact_b = make_contact(committed_db, phone="+15550800002")
    tag = _make_tag(committed_db, "VIP", "#aabbcc")
    _apply_tag(committed_db, contact_a, tag)
    conv_a = make_conversation(committed_db, contact=contact_a)
    make_conversation(committed_db, contact=contact_b)  # untagged
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/conversations?tag_id={tag.id}", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [str(conv_a.id)]
    assert body["items"][0]["tags"] == [
        {"id": str(tag.id), "name": "VIP", "color": "#aabbcc"}
    ]


@pytest.mark.asyncio
async def test_rows_include_all_tags_sorted_by_name(committed_db, client):
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db, phone="+15550800003")
    t_zeta = _make_tag(committed_db, "Zeta", "#000001")
    t_alpha = _make_tag(committed_db, "Alpha", "#000002")
    _apply_tag(committed_db, contact, t_zeta)
    _apply_tag(committed_db, contact, t_alpha)
    conv = make_conversation(committed_db, contact=contact)
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/conversations?contact_id={contact.id}", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    row = next(i for i in resp.json()["items"] if i["id"] == str(conv.id))
    assert [t["name"] for t in row["tags"]] == ["Alpha", "Zeta"]


@pytest.mark.asyncio
async def test_rows_with_no_tags_yield_empty_list(committed_db, client):
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db, phone="+15550800004")
    conv = make_conversation(committed_db, contact=contact)
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/conversations?contact_id={contact.id}", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    row = next(i for i in resp.json()["items"] if i["id"] == str(conv.id))
    assert row["tags"] == []
