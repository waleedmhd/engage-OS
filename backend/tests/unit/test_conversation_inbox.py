"""Phase 5 tests for the enriched inbox listing.

Confirms that GET /api/v1/conversations now returns Page[ConversationListItem]
with the contact summary + last-message preview, dispatched via
ConversationRepository.list_inbox.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import (
    get_current_user_claims,
    get_current_user_db,
    get_db_session,
)


@pytest.fixture(autouse=True)
def stub_db_session(app):
    async def _fake_session():
        yield AsyncMock()
    app.dependency_overrides[get_db_session] = _fake_session
    yield
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def override_user(app):
    user_id = uuid.uuid4()

    async def _claims() -> dict:
        return {"sub": str(user_id), "role": "agent", "iat": 0, "exp": 9999999999}

    user = MagicMock()
    user.id = user_id
    user.role = "agent"

    async def _user() -> object:
        return user

    app.dependency_overrides[get_current_user_claims] = _claims
    app.dependency_overrides[get_current_user_db] = _user
    yield user_id
    app.dependency_overrides.pop(get_current_user_claims, None)
    app.dependency_overrides.pop(get_current_user_db, None)


@pytest.mark.asyncio
async def test_inbox_list_returns_enriched_items(app, override_user, monkeypatch):
    """list_inbox response is shaped into Page[ConversationListItem]."""
    conv_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    msg_id = uuid.uuid4()

    rows = [
        {
            "id": conv_id,
            "state": "AI_ACTIVE",
            "ai_enabled": True,
            "locked_by": None,
            "lock_expires_at": None,
            "last_message_at": datetime.now(UTC),
            "unread": False,
            "contact": {
                "id": contact_id,
                "name": "Acme",
                "phone": "+15550001111",
                "assigned_agent_id": None,
            },
            "last_message": {
                "id": msg_id,
                "direction": "inbound",
                "content": "hi",
                "created_at": datetime.now(UTC),
            },
        }
    ]

    fake_repo = MagicMock()
    fake_repo.list_inbox = AsyncMock(return_value=(rows, 1))

    from app.modules.conversations import router as conv_router_module
    monkeypatch.setattr(
        conv_router_module, "ConversationRepository", lambda _s: fake_repo
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get(
            "/api/v1/conversations?state=AI_ACTIVE&page=1&page_size=20",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    item = body["items"][0]
    assert item["id"] == str(conv_id)
    assert item["unread"] is False
    assert item["contact"]["phone"] == "+1 555 000 1111"
    assert item["last_message"]["content"] == "hi"

    # Repository was called with the parsed query filters.
    call = fake_repo.list_inbox.await_args
    assert call.kwargs["state"] == "AI_ACTIVE"
    assert call.kwargs["limit"] == 20
    assert call.kwargs["offset"] == 0


@pytest.mark.asyncio
async def test_inbox_handles_no_messages(app, override_user, monkeypatch):
    """Conversation with no messages → last_message is null in response."""
    rows = [
        {
            "id": uuid.uuid4(),
            "state": "NEW",
            "ai_enabled": True,
            "locked_by": None,
            "lock_expires_at": None,
            "last_message_at": None,
            "unread": False,
            "contact": {
                "id": uuid.uuid4(),
                "name": None,
                "phone": "+15550009999",
                "assigned_agent_id": None,
            },
            "last_message": None,
        }
    ]
    fake_repo = MagicMock()
    fake_repo.list_inbox = AsyncMock(return_value=(rows, 1))

    from app.modules.conversations import router as conv_router_module
    monkeypatch.setattr(
        conv_router_module, "ConversationRepository", lambda _s: fake_repo
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get(
            "/api/v1/conversations",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["last_message"] is None


@pytest.mark.asyncio
async def test_inbox_list_includes_tags_and_forwards_tag_id(
    app, override_user, monkeypatch
):
    """Row tags are serialized and ?tag_id= is forwarded to the repository."""
    conv_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    tag_id = uuid.uuid4()

    rows = [
        {
            "id": conv_id,
            "state": "AI_ACTIVE",
            "ai_enabled": True,
            "locked_by": None,
            "lock_expires_at": None,
            "last_message_at": datetime.now(UTC),
            "unread": False,
            "contact": {
                "id": contact_id,
                "name": "Acme",
                "phone": "+15550001111",
                "assigned_agent_id": None,
            },
            "last_message": None,
            "tags": [{"id": tag_id, "name": "VIP", "color": "#aabbcc"}],
        }
    ]

    fake_repo = MagicMock()
    fake_repo.list_inbox = AsyncMock(return_value=(rows, 1))

    from app.modules.conversations import router as conv_router_module
    monkeypatch.setattr(
        conv_router_module, "ConversationRepository", lambda _s: fake_repo
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get(
            f"/api/v1/conversations?tag_id={tag_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["tags"] == [
        {"id": str(tag_id), "name": "VIP", "color": "#aabbcc"}
    ]
    assert fake_repo.list_inbox.await_args.kwargs["tag_id"] == tag_id


@pytest.mark.asyncio
async def test_inbox_unread_flag_serialized(app, override_user, monkeypatch):
    """Conversations with unread=True are serialized correctly."""
    rows = [
        {
            "id": uuid.uuid4(),
            "state": "AI_ACTIVE",
            "ai_enabled": True,
            "locked_by": None,
            "lock_expires_at": None,
            "last_message_at": datetime.now(UTC),
            "unread": True,
            "contact": {
                "id": uuid.uuid4(),
                "name": "Unread Contact",
                "phone": "+15550002222",
                "assigned_agent_id": None,
            },
            "last_message": None,
        }
    ]

    fake_repo = MagicMock()
    fake_repo.list_inbox = AsyncMock(return_value=(rows, 1))

    from app.modules.conversations import router as conv_router_module
    monkeypatch.setattr(
        conv_router_module, "ConversationRepository", lambda _s: fake_repo
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get(
            "/api/v1/conversations",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["unread"] is True
