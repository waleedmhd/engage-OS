"""Router-level tests for the categorization endpoints (DSD §6.2).

The service is monkeypatched so the test isolates the router and dependency
wiring; the service layer is covered by test_categorization_service.py.
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
from app.core.exceptions import NotFoundError, StateTransitionError
from app.modules.categorization.constants import TagSuggestionStatus

# ----------------------------------------------------------------- helpers


def _make_tag(**overrides):
    t = MagicMock()
    t.id = overrides.get("id", uuid.uuid4())
    t.name = overrides.get("name", "Buyer")
    t.description = overrides.get("description", None)
    t.created_at = overrides.get("created_at", datetime.now(UTC))
    return t


def _make_suggestion(**overrides):
    s = MagicMock()
    s.id = overrides.get("id", uuid.uuid4())
    s.contact_id = overrides.get("contact_id", uuid.uuid4())
    s.tag_id = overrides.get("tag_id", uuid.uuid4())
    s.confidence = overrides.get("confidence", 0.92)
    s.reason = overrides.get("reason", "buyer_intent")
    s.status = overrides.get("status", TagSuggestionStatus.PENDING.value)
    s.reviewed_by = overrides.get("reviewed_by", None)
    s.reviewed_at = overrides.get("reviewed_at", None)
    s.created_at = overrides.get("created_at", datetime.now(UTC))
    return s


def _make_contact_tag(**overrides):
    ct = MagicMock()
    ct.contact_id = overrides.get("contact_id", uuid.uuid4())
    ct.tag_id = overrides.get("tag_id", uuid.uuid4())
    ct.approved_by = overrides.get("approved_by", uuid.uuid4())
    ct.approved_at = overrides.get("approved_at", datetime.now(UTC))
    return ct


# ----------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def stub_db_session(app):
    """The service is mocked, so the session itself is never consumed."""
    async def _fake_session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _fake_session
    yield
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def override_user(app):
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


@pytest.fixture
def patch_service(monkeypatch):
    """Replace `CategorizationService` in the router module with a factory
    that returns a single MagicMock so tests can configure await returns."""
    fake = MagicMock()

    from app.modules.categorization import router as router_module

    monkeypatch.setattr(
        router_module, "CategorizationService", lambda _session: fake
    )
    return fake


# --------------------------------------------------------------- auth gates


@pytest.mark.asyncio
async def test_endpoints_require_authentication(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.get("/api/v1/categorization/tags")
        r2 = await ac.get("/api/v1/categorization/tag-suggestions")
        r3 = await ac.post(f"/api/v1/categorization/tag-suggestions/{uuid.uuid4()}/approve")
        r4 = await ac.post(f"/api/v1/categorization/tag-suggestions/{uuid.uuid4()}/reject")
    for r in (r1, r2, r3, r4):
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_endpoints_reject_unknown_role(app, override_user, patch_service):
    override_user("viewer")
    from app.modules.categorization.schemas import TagListResponse

    patch_service.list_tags_paginated = AsyncMock(
        return_value=TagListResponse(items=[], total=0, limit=100, offset=0)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/api/v1/categorization/tags",
            headers={"Authorization": "Bearer dummy"},
        )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


# ------------------------------------------------------------------ GET /tags


@pytest.mark.asyncio
async def test_list_tags_returns_paginated_envelope(app, override_user, patch_service):
    override_user("agent")
    from app.modules.categorization.schemas import (
        TagListResponse,
        TagWithUsageResponse,
    )

    items = [
        TagWithUsageResponse.model_validate(
            {
                **_make_tag(name="Buyer").__dict__,
                "id": uuid.uuid4(),
                "name": "Buyer",
                "description": None,
                "color": None,
                "created_at": datetime.now(UTC),
                "usage_count": 3,
            }
        ),
        TagWithUsageResponse.model_validate(
            {
                "id": uuid.uuid4(),
                "name": "Seller",
                "description": None,
                "color": "#ff0000",
                "created_at": datetime.now(UTC),
                "usage_count": 0,
            }
        ),
    ]
    patch_service.list_tags_paginated = AsyncMock(
        return_value=TagListResponse(items=items, total=2, limit=100, offset=0)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/api/v1/categorization/tags",
            headers={"Authorization": "Bearer dummy"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {t["name"] for t in body["items"]} == {"Buyer", "Seller"}
    assert body["limit"] == 100
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_create_tag_admin_only_403_for_agent(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/categorization/tags",
            json={"name": "vip"},
            headers={"Authorization": "Bearer dummy"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_tag_admin_201(app, override_user, patch_service):
    override_user("admin")
    from app.modules.categorization.schemas import TagResponse

    fake = TagResponse(
        id=uuid.uuid4(),
        name="vip",
        description=None,
        color="#ff0000",
        created_at=datetime.now(UTC),
    )
    patch_service.create_tag = AsyncMock(return_value=fake)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/categorization/tags",
            json={"name": "vip", "color": "#ff0000"},
            headers={"Authorization": "Bearer dummy"},
        )
    assert r.status_code == 201
    assert r.json()["color"] == "#ff0000"


@pytest.mark.asyncio
async def test_delete_tag_admin_only_204(app, override_user, patch_service):
    override_user("admin")
    patch_service.delete_tag = AsyncMock(return_value=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.delete(
            f"/api/v1/categorization/tags/{uuid.uuid4()}",
            headers={"Authorization": "Bearer dummy"},
        )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_tag_agent_forbidden(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.delete(
            f"/api/v1/categorization/tags/{uuid.uuid4()}",
            headers={"Authorization": "Bearer dummy"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_update_tag_empty_body_returns_409(app, override_user, patch_service):
    override_user("admin")
    from app.core.exceptions import ConflictError

    patch_service.update_tag = AsyncMock(side_effect=ConflictError("no_changes"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch(
            f"/api/v1/categorization/tags/{uuid.uuid4()}",
            json={},
            headers={"Authorization": "Bearer dummy"},
        )
    assert r.status_code == 409


# --------------------------------------------- GET /contacts/{id}/tags


@pytest.mark.asyncio
async def test_list_contact_tags_200(app, override_user, patch_service):
    override_user("agent")
    contact_id = uuid.uuid4()
    link = _make_contact_tag(contact_id=contact_id)
    patch_service.list_contact_tags = AsyncMock(return_value=[link])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            f"/api/v1/categorization/contacts/{contact_id}/tags",
            headers={"Authorization": "Bearer dummy"},
        )

    # If FastAPI routed this to the contacts router by mistake, the response
    # would be 404 (no /{id}/tags subpath there) rather than 200 with the
    # serialized link payload.
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["contact_id"] == str(contact_id)
    patch_service.list_contact_tags.assert_awaited_once_with(contact_id)


# ----------------------------- POST/DELETE /contacts/{id}/tags/{tag_id}


@pytest.mark.asyncio
async def test_apply_contact_tag_204(app, override_user, patch_service):
    user_id = override_user("agent")
    contact_id = uuid.uuid4()
    tag_id = uuid.uuid4()
    patch_service.apply_tag = AsyncMock(return_value=None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/contacts/{contact_id}/tags/{tag_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 204, r.text
    patch_service.apply_tag.assert_awaited_once()
    call = patch_service.apply_tag.await_args
    assert call.args[0] == contact_id
    assert call.args[1] == tag_id
    assert call.kwargs["actor_id"] == user_id


@pytest.mark.asyncio
async def test_apply_contact_tag_unknown_tag_404(app, override_user, patch_service):
    override_user("agent")
    patch_service.apply_tag = AsyncMock(
        side_effect=NotFoundError(f"Tag:{uuid.uuid4()}")
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/contacts/{uuid.uuid4()}/tags/{uuid.uuid4()}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_apply_contact_tag_requires_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/contacts/{uuid.uuid4()}/tags/{uuid.uuid4()}"
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_apply_contact_tag_rejects_unknown_role(
    app, override_user, patch_service
):
    override_user("viewer")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/contacts/{uuid.uuid4()}/tags/{uuid.uuid4()}",
            headers={"Authorization": "Bearer dummy"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_remove_contact_tag_204(app, override_user, patch_service):
    user_id = override_user("agent")
    contact_id = uuid.uuid4()
    tag_id = uuid.uuid4()
    patch_service.remove_tag = AsyncMock(return_value=None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.delete(
            f"/api/v1/categorization/contacts/{contact_id}/tags/{tag_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 204, r.text
    patch_service.remove_tag.assert_awaited_once()
    call = patch_service.remove_tag.await_args
    assert call.args[0] == contact_id
    assert call.args[1] == tag_id
    assert call.kwargs["actor_id"] == user_id


# ----------------------------------------------------- GET /tag-suggestions


@pytest.mark.asyncio
async def test_list_tag_suggestions_default_filters(
    app, override_user, patch_service
):
    override_user("agent")
    patch_service.list_suggestions = AsyncMock(return_value=([_make_suggestion()], 1))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/api/v1/categorization/tag-suggestions",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["total"] == 1
    assert len(body["items"]) == 1

    # No status query param → service receives status=None and applies its
    # own pending default.
    kwargs = patch_service.list_suggestions.await_args.kwargs
    assert kwargs["status"] is None
    assert kwargs["contact_id"] is None
    assert kwargs["page"] == 1
    assert kwargs["page_size"] == 50


@pytest.mark.asyncio
async def test_list_tag_suggestions_with_filters(app, override_user, patch_service):
    override_user("agent")
    contact_id = uuid.uuid4()
    patch_service.list_suggestions = AsyncMock(return_value=([], 0))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            f"/api/v1/categorization/tag-suggestions?status=approved&contact_id={contact_id}"
            "&page=2&page_size=10",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 200
    kwargs = patch_service.list_suggestions.await_args.kwargs
    assert kwargs["status"] == "approved"
    assert kwargs["contact_id"] == contact_id
    assert kwargs["page"] == 2
    assert kwargs["page_size"] == 10


# -------------------------------------------------------------- POST /approve


@pytest.mark.asyncio
async def test_approve_tag_suggestion_200(app, override_user, patch_service):
    user_id = override_user("agent")
    sid = uuid.uuid4()
    approved = _make_suggestion(
        id=sid,
        status=TagSuggestionStatus.APPROVED.value,
        reviewed_by=user_id,
        reviewed_at=datetime.now(UTC),
    )
    patch_service.approve = AsyncMock(return_value=approved)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/tag-suggestions/{sid}/approve",
            json={"note": "fits the buyer profile"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(sid)
    assert body["status"] == TagSuggestionStatus.APPROVED.value

    patch_service.approve.assert_awaited_once()
    call = patch_service.approve.await_args
    assert call.args[0] == sid
    assert call.kwargs["reviewer_id"] == user_id
    assert call.kwargs["note"] == "fits the buyer profile"


@pytest.mark.asyncio
async def test_approve_without_body_succeeds(app, override_user, patch_service):
    user_id = override_user("agent")
    sid = uuid.uuid4()
    patch_service.approve = AsyncMock(
        return_value=_make_suggestion(id=sid, status=TagSuggestionStatus.APPROVED.value)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/tag-suggestions/{sid}/approve",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 200
    assert patch_service.approve.await_args.kwargs["note"] is None
    assert patch_service.approve.await_args.kwargs["reviewer_id"] == user_id


@pytest.mark.asyncio
async def test_approve_not_pending_returns_409(app, override_user, patch_service):
    override_user("agent")
    patch_service.approve = AsyncMock(
        side_effect=StateTransitionError(
            "only pending suggestions can be approved",
            details={"current_status": "approved"},
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/tag-suggestions/{uuid.uuid4()}/approve",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "state_transition_error"


@pytest.mark.asyncio
async def test_approve_missing_returns_404(app, override_user, patch_service):
    override_user("agent")
    patch_service.approve = AsyncMock(
        side_effect=NotFoundError(f"TagSuggestion:{uuid.uuid4()}")
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/tag-suggestions/{uuid.uuid4()}/approve",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# -------------------------------------------------------------- POST /reject


@pytest.mark.asyncio
async def test_reject_tag_suggestion_200(app, override_user, patch_service):
    user_id = override_user("agent")
    sid = uuid.uuid4()
    rejected = _make_suggestion(
        id=sid,
        status=TagSuggestionStatus.REJECTED.value,
        reviewed_by=user_id,
        reviewed_at=datetime.now(UTC),
    )
    patch_service.reject = AsyncMock(return_value=rejected)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/tag-suggestions/{sid}/reject",
            json={"note": "off-topic"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == TagSuggestionStatus.REJECTED.value
    assert patch_service.reject.await_args.kwargs["note"] == "off-topic"


@pytest.mark.asyncio
async def test_reject_not_pending_returns_409(app, override_user, patch_service):
    override_user("agent")
    patch_service.reject = AsyncMock(
        side_effect=StateTransitionError(
            "only pending suggestions can be rejected",
            details={"current_status": "rejected"},
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/tag-suggestions/{uuid.uuid4()}/reject",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 409


# ----------------------------------------------------- admin role accepted


@pytest.mark.asyncio
async def test_admin_role_can_approve(app, override_user, patch_service):
    user_id = override_user("admin")
    sid = uuid.uuid4()
    patch_service.approve = AsyncMock(
        return_value=_make_suggestion(id=sid, status=TagSuggestionStatus.APPROVED.value)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/categorization/tag-suggestions/{sid}/approve",
            headers={"Authorization": "Bearer dummy"},
        )

    assert r.status_code == 200
    assert patch_service.approve.await_args.kwargs["reviewer_id"] == user_id
