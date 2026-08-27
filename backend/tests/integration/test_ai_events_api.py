"""Integration tests for GET /api/v1/ai/events/{conversation_id}.

Seeds AIEvent rows via the real-committing `committed_db` and drives the
HTTP API with a real admin JWT (DSD §10 admin observability surface).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.security import create_access_token
from tests.factories import (
    make_ai_event,
    make_contact,
    make_conversation,
    make_user,
)


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.mark.asyncio
async def test_ai_events_paginated_real_total(committed_db, client):
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db)
    conv = make_conversation(committed_db, contact=contact)
    for i in range(7):
        make_ai_event(
            committed_db,
            conversation=conv,
            intent="faq",
            confidence=0.9,
            latency_ms=100 + i,
            cost_estimate=0.0,
            request={"incoming_message": f"q-{i}"},
            response={"reply": f"a-{i}", "confidence": 0.9},
        )
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/ai/events/{conv.id}?page=1&page_size=3", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 7
    assert body["page"] == 1
    assert body["page_size"] == 3
    assert len(body["items"]) == 3
    # newest-first ordering
    assert body["items"][0]["request"]["incoming_message"] == "q-6"


@pytest.mark.asyncio
async def test_ai_events_scoped_to_conversation(committed_db, client):
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db)
    conv_a = make_conversation(committed_db, contact=contact)
    conv_b = make_conversation(committed_db, contact=contact)
    make_ai_event(committed_db, conversation=conv_a)
    make_ai_event(committed_db, conversation=conv_a)
    make_ai_event(committed_db, conversation=conv_b)
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/ai/events/{conv_a.id}", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_ai_events_admin_only(committed_db, client):
    agent = make_user(committed_db, role="agent")
    contact = make_contact(committed_db)
    conv = make_conversation(committed_db, contact=contact)
    committed_db.commit()

    resp = await client.get(f"/api/v1/ai/events/{conv.id}", headers=_token(agent))
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_ai_events_empty_returns_zero_total(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/ai/events/{uuid.uuid4()}", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []
