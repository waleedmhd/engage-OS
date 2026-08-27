"""Integration tests for POST /contacts/upsert.

Drives router -> repository against a real Postgres via `committed_db`,
with real JWTs minted via `create_access_token`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.modules.contacts.models import Contact
from tests.factories import make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.mark.asyncio
async def test_upsert_creates_new_contact(committed_db, client):
    """First upsert creates a contact with phone, name, and information."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    resp = await client.post(
        "/api/v1/contacts/upsert",
        json={"phone": "+15551110001", "name": "Ahmed Trader"},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phone"] == "+1 555 111 0001"
    assert body["name"] == "Ahmed Trader"

    # Verify row in DB
    contact = committed_db.execute(
        select(Contact).where(Contact.phone == "15551110001")
    ).scalar_one()
    assert contact.name == "Ahmed Trader"


@pytest.mark.asyncio
async def test_upsert_updates_existing_and_appends_information(committed_db, client):
    """Repeated upsert for the same phone appends to information."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    # First upsert — creates with initial info
    await client.post(
        "/api/v1/contacts/upsert",
        json={
            "phone": "+15551110002",
            "name": "Sara Seller",
            "information": "Intent: WTS | Brand: Samsung",
        },
        headers=h,
    )

    # Second upsert — appends more info
    resp = await client.post(
        "/api/v1/contacts/upsert",
        json={
            "phone": "+15551110002",
            "information": "Intent: WTB | Brand: Apple | Storage: 256GB",
        },
        headers=h,
    )
    assert resp.status_code == 200, resp.text

    contact = committed_db.execute(
        select(Contact).where(Contact.phone == "15551110002")
    ).scalar_one()

    # Name should NOT be overwritten by the second call (no name in payload)
    assert contact.name == "Sara Seller"
    # Information should contain both entries
    assert "WTS | Brand: Samsung" in contact.information
    assert "WTB | Brand: Apple | Storage: 256GB" in contact.information
    # Separator should be present
    assert "\n\n---\n\n" in contact.information


@pytest.mark.asyncio
async def test_upsert_does_not_overwrite_name(committed_db, client):
    """Name is only set on creation; subsequent upserts don't overwrite it."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    # Create with name "Ahmed Al-Rashid Trading LLC"
    await client.post(
        "/api/v1/contacts/upsert",
        json={"phone": "+15551110003", "name": "Ahmed Al-Rashid Trading LLC"},
        headers=h,
    )

    # Upsert with a different name (e.g. from WhatsApp pushname "Ahmed")
    await client.post(
        "/api/v1/contacts/upsert",
        json={
            "phone": "+15551110003",
            "name": "Ahmed",
            "information": "Intent: WTB | Brand: Apple",
        },
        headers=h,
    )

    contact = committed_db.execute(
        select(Contact).where(Contact.phone == "15551110003")
    ).scalar_one()
    assert contact.name == "Ahmed Al-Rashid Trading LLC"
    assert "WTB | Brand: Apple" in contact.information


@pytest.mark.asyncio
async def test_upsert_requires_authentication(committed_db, client):
    """No token → 401."""
    resp = await client.post(
        "/api/v1/contacts/upsert",
        json={"phone": "+15551110004"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upsert_rejects_invalid_phone(committed_db, client):
    """Phone < 4 chars → 422."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    resp = await client.post(
        "/api/v1/contacts/upsert",
        json={"phone": "12"},
        headers=h,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upsert_agent_can_upsert(committed_db, client):
    """An agent (not admin) can also upsert contacts."""
    agent = make_user(committed_db, role="agent")
    committed_db.commit()
    h = _token(agent)

    resp = await client.post(
        "/api/v1/contacts/upsert",
        json={"phone": "+15551110005", "name": "Test"},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["phone"] == "+1 555 111 0005"
