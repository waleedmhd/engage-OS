"""Router-level tests for contacts endpoints (Phase 5).

Covers role gating and happy-path dispatch into ContactService. The
service is mocked so the test isolates the router and dependency wiring;
integration tests against a real DB live in tests/integration/.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import (
    get_current_user_claims,
    get_current_user_db,
    get_db_session,
)


def _make_contact(**overrides):
    """A bare object with the attributes ContactResponse.model_validate reads."""
    base = MagicMock()
    base.id = overrides.get("id", uuid.uuid4())
    base.phone = overrides.get("phone", "15551234567")
    base.name = overrides.get("name", "Acme")
    base.company = overrides.get("company", "Acme Co")
    base.status = overrides.get("status", "active")
    base.notes = overrides.get("notes", None)
    base.information = overrides.get("information", None)
    base.ai_assigned = overrides.get("ai_assigned", False)
    base.assigned_agent_id = overrides.get("assigned_agent_id", None)
    base.revenue_attributed = overrides.get("revenue_attributed", Decimal("0"))
    base.estimated_ltv = overrides.get("estimated_ltv", None)
    base.last_interaction_at = overrides.get("last_interaction_at", None)
    base.last_contacted_at = overrides.get("last_contacted_at", None)
    base.last_inbound_at = overrides.get("last_inbound_at", None)
    base.conversation_count = overrides.get("conversation_count", 0)
    base.created_at = overrides.get("created_at", datetime.now(UTC))
    base.updated_at = overrides.get("updated_at", datetime.now(UTC))
    # The list endpoint resolves tag chips from the eager-loaded relationship.
    base.contact_tags = overrides.get("contact_tags", [])
    base.tags = overrides.get("tags", [])
    return base


@pytest.fixture(autouse=True)
def stub_db_session(app):
    """Override get_db_session with a no-op AsyncMock; the service is mocked
    too, so the session is never actually consumed."""
    async def _fake_session():
        yield AsyncMock()
    app.dependency_overrides[get_db_session] = _fake_session
    yield
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def override_user(app):
    """Wire both the JWT claims and the User ORM dependency for one test."""
    user_id = uuid.uuid4()

    def _set(role: str = "agent") -> uuid.UUID:
        async def _claims() -> dict:
            return {"sub": str(user_id), "role": role, "iat": 0, "exp": 9999999999}

        user = MagicMock()
        user.id = user_id
        user.role = role

        async def _user() -> object:
            return user

        app.dependency_overrides[get_current_user_claims] = _claims
        app.dependency_overrides[get_current_user_db] = _user
        return user_id

    yield _set
    app.dependency_overrides.pop(get_current_user_claims, None)
    app.dependency_overrides.pop(get_current_user_db, None)


# ----------------------------------------------------------- role gates

@pytest.mark.asyncio
async def test_list_requires_authentication(app):
    """No bearer token → 401 from get_current_user_claims."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/contacts")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_returns_page_envelope(app, override_user, monkeypatch):
    """Happy path: ContactService.list_contacts returns (items, total)."""
    override_user("agent")

    fake_service = MagicMock()
    fake_service.list_contacts = AsyncMock(return_value=([_make_contact(), _make_contact()], 7))

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactService", lambda _session: fake_service
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get(
            "/api/v1/contacts?page=2&page_size=25&q=acme&status=active",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["page_size"] == 25
    assert body["total"] == 7
    assert len(body["items"]) == 2

    # Verify the service was called with parsed filter values.
    call = fake_service.list_contacts.await_args
    assert call.kwargs["page"] == 2
    assert call.kwargs["page_size"] == 25
    assert call.kwargs["filters"].q == "acme"
    assert call.kwargs["filters"].status == "active"


@pytest.mark.asyncio
async def test_create_contact_returns_201(app, override_user, monkeypatch):
    """POST /contacts with a fresh phone returns 201 + ContactResponse."""
    override_user("agent")

    new_contact = _make_contact(phone="15550009999")
    fake_service = MagicMock()
    fake_service.create_contact = AsyncMock(return_value=new_contact)

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactService", lambda _session: fake_service
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts",
            json={"phone": "+15550009999", "name": "New"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["phone"] == "+1 555 000 9999"


@pytest.mark.asyncio
async def test_create_contact_admin_can_assign_agent(app, override_user, monkeypatch):
    """Admin may set status + assigned_agent_id on create; both reach the service."""
    override_user("admin")

    agent_id = uuid.uuid4()
    new_contact = _make_contact(
        phone="15550001111", status="inactive", assigned_agent_id=agent_id
    )
    fake_service = MagicMock()
    fake_service.create_contact = AsyncMock(return_value=new_contact)

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactService", lambda _session: fake_service
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts",
            json={
                "phone": "+15550001111",
                "status": "inactive",
                "assigned_agent_id": str(agent_id),
            },
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 201
    call = fake_service.create_contact.await_args
    assert call.kwargs["payload"].assigned_agent_id == agent_id
    assert call.kwargs["payload"].status == "inactive"


@pytest.mark.asyncio
async def test_create_contact_agent_cannot_assign_agent(app, override_user, monkeypatch):
    """A non-admin including assigned_agent_id gets 400 assign_admin_only."""
    override_user("agent")

    fake_service = MagicMock()
    fake_service.create_contact = AsyncMock()

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactService", lambda _session: fake_service
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts",
            json={"phone": "+15550002222", "assigned_agent_id": str(uuid.uuid4())},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "assign_admin_only"
    fake_service.create_contact.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_contact_invalid_status_rejected(app, override_user):
    """Create-request status validator rejects values outside the StrEnum."""
    override_user("agent")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts",
            json={"phone": "+15550003333", "status": "garbage"},
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_contact_dispatches_partial_payload(app, override_user, monkeypatch):
    """PATCH only sends the fields the caller supplied (exclude_unset)."""
    override_user("agent")

    contact_id = uuid.uuid4()
    updated = _make_contact(id=contact_id, notes="hello")
    fake_service = MagicMock()
    fake_service.update_contact = AsyncMock(return_value=updated)

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactService", lambda _session: fake_service
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.patch(
            f"/api/v1/contacts/{contact_id}",
            json={"notes": "hello"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    assert response.json()["notes"] == "hello"

    # Service got the typed payload, not the raw dict.
    call = fake_service.update_contact.await_args
    assert call.kwargs["contact_id"] == contact_id
    assert call.kwargs["payload"].notes == "hello"
    # Unset fields stay absent (model_dump(exclude_unset=True) responsibility
    # belongs to the service, but the schema parsed it correctly).
    dumped = call.kwargs["payload"].model_dump(exclude_unset=True)
    assert dumped == {"notes": "hello"}


@pytest.mark.asyncio
async def test_invalid_status_rejected_by_validator(app, override_user):
    """Status validator rejects values outside the StrEnum."""
    override_user("agent")

    contact_id = uuid.uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.patch(
            f"/api/v1/contacts/{contact_id}",
            json={"status": "garbage"},
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == 422


# ----------------------------------------------------------- upsert endpoint


@pytest.mark.asyncio
async def test_upsert_requires_authentication(app):
    """No bearer token → 401 from get_current_user_claims."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/v1/contacts/upsert")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upsert_creates_new_contact(app, override_user, monkeypatch):
    """POST /contacts/upsert with a new phone returns 200 + ContactResponse."""
    override_user("agent")

    new_contact = _make_contact(phone="15550008888", name="New Contact")
    fake_repo = MagicMock()
    fake_repo.upsert_by_phone_append = AsyncMock(return_value=new_contact)
    fake_repo.get_by_phone = AsyncMock(return_value=new_contact)

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactRepository", lambda _session: fake_repo
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts/upsert",
            json={"phone": "+15550008888", "name": "New Contact"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1 555 000 8888"
    # Verify the repo was called with canonicalized phone
    call = fake_repo.upsert_by_phone_append.await_args
    assert call.kwargs["phone"] == "15550008888"
    assert call.kwargs["name"] == "New Contact"


@pytest.mark.asyncio
async def test_upsert_appends_information(app, override_user, monkeypatch):
    """POST /contacts/upsert passes information to the append method."""
    override_user("agent")

    existing = _make_contact(phone="15550009999", name="Ahmed")
    existing.information = "Prior info"
    fake_repo = MagicMock()
    fake_repo.upsert_by_phone_append = AsyncMock(return_value=existing)
    fake_repo.get_by_phone = AsyncMock(return_value=existing)

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactRepository", lambda _session: fake_repo
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts/upsert",
            json={
                "phone": "+15550009999",
                "information": "Intent: WTB | Brand: Apple | Storage: 256GB",
            },
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    call = fake_repo.upsert_by_phone_append.await_args
    assert call.kwargs["phone"] == "15550009999"
    assert call.kwargs["information"] == "Intent: WTB | Brand: Apple | Storage: 256GB"


@pytest.mark.asyncio
async def test_upsert_phone_canonicalization(app, override_user, monkeypatch):
    """Phones like "+971 50 123 4567" are canonicalized to digits before upsert."""
    override_user("agent")

    contact = _make_contact(phone="971501234567")
    fake_repo = MagicMock()
    fake_repo.upsert_by_phone_append = AsyncMock(return_value=contact)
    fake_repo.get_by_phone = AsyncMock(return_value=contact)

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactRepository", lambda _session: fake_repo
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts/upsert",
            json={"phone": "+971 50 123-4567"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    call = fake_repo.upsert_by_phone_append.await_args
    assert call.kwargs["phone"] == "971501234567"


@pytest.mark.asyncio
async def test_upsert_phone_too_short_rejected(app, override_user):
    """Empty phone or < 4 chars is rejected by schema validation."""
    override_user("agent")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts/upsert",
            json={"phone": "12"},
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == 422
