"""Integration tests for chat history JSONL export."""

from __future__ import annotations

import json

import pytest

from app.core.security import create_access_token
from tests.factories import make_contact, make_conversation, make_message, make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.mark.asyncio
async def test_export_returns_jsonl_with_conversations(committed_db, client):
    """A conversation with messages produces one JSONL line with correct fields."""
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db, name="Alice", phone="+15551112222")
    conv = make_conversation(committed_db, contact=contact)
    make_message(committed_db, conversation=conv, direction="inbound", sender_type="contact", content="Hello")
    make_message(committed_db, conversation=conv, direction="outbound", sender_type="ai", content="Hi there!")
    committed_db.commit()

    r = await client.get("/api/v1/settings/export/chat-history", headers=_token(admin))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/x-jsonlines"
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].startswith('attachment; filename="chat-history-')

    lines = r.text.strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])

    assert data["conversation_id"] == str(conv.id)
    assert data["contact"]["name"] == "Alice"
    assert data["contact"]["phone"] == "+15551112222"
    assert data["state"] == conv.state
    assert data["ai_enabled"] is True
    assert len(data["messages"]) == 2
    assert data["messages"][0]["content"] == "Hello"
    assert data["messages"][0]["direction"] == "inbound"
    assert data["messages"][1]["content"] == "Hi there!"
    assert data["messages"][1]["sender_type"] == "ai"


@pytest.mark.asyncio
async def test_export_empty_returns_comment(committed_db, client):
    """When no conversations exist, the response is a comment line."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()

    r = await client.get("/api/v1/settings/export/chat-history", headers=_token(admin))
    assert r.status_code == 200, r.text
    assert r.text.strip() == "# No conversations with messages found."


@pytest.mark.asyncio
async def test_export_skips_empty_conversations(committed_db, client):
    """Conversations with no messages are excluded from the export."""
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db)
    make_conversation(committed_db, contact=contact)  # no messages
    committed_db.commit()

    r = await client.get("/api/v1/settings/export/chat-history", headers=_token(admin))
    assert r.status_code == 200
    assert r.text.strip() == "# No conversations with messages found."


@pytest.mark.asyncio
async def test_export_admin_only(committed_db, client):
    """Non-admin users get 403."""
    agent = make_user(committed_db, role="agent")
    committed_db.commit()

    r = await client.get("/api/v1/settings/export/chat-history", headers=_token(agent))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_export_unicode_content(committed_db, client):
    """Messages with emoji and non-ASCII text are exported correctly."""
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db, name="José", phone="+15559998888")
    conv = make_conversation(committed_db, contact=contact)
    make_message(committed_db, conversation=conv, content="Gracias 🙏 — ¿cómo estás?")
    committed_db.commit()

    r = await client.get("/api/v1/settings/export/chat-history", headers=_token(admin))
    assert r.status_code == 200, r.text
    data = json.loads(r.text.strip().split("\n")[0])
    assert data["messages"][0]["content"] == "Gracias 🙏 — ¿cómo estás?"
