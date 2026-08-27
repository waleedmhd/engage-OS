"""Router-level tests for /api/v1/users.

Service is monkeypatched; UserService behaviour is covered by
test_users_service.py.
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
from app.modules.users.schemas import (
    UserListResponse,
    UserResponse,
    UserSectionsResponse,
)


def _u(role="agent") -> UserResponse:
    return UserResponse(
        id=uuid.uuid4(),
        email="a@b.com",
        name="N",
        role=role,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
def stub_db_session(app):
    session = AsyncMock()
    session.commit = AsyncMock()

    async def _fake_session():
        yield session

    app.dependency_overrides[get_db_session] = _fake_session
    app.state._test_session = session
    yield
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def override_user(app):
    def _set(role: str = "admin") -> None:
        uid = uuid.uuid4()

        async def _claims() -> dict:
            return {"sub": str(uid), "role": role, "iat": 0, "exp": 9999999999}

        user = MagicMock()
        user.id = uid
        user.role = role

        async def _user() -> object:
            return user

        app.dependency_overrides[get_current_user_claims] = _claims
        app.dependency_overrides[get_current_user_db] = _user

    yield _set
    app.dependency_overrides.pop(get_current_user_claims, None)
    app.dependency_overrides.pop(get_current_user_db, None)


@pytest.fixture
def patch_service(monkeypatch):
    fake = MagicMock()
    from app.modules.users import router as router_module

    monkeypatch.setattr(router_module, "UserService", lambda _s: fake)
    return fake


# -------------------------------------------------------------------- auth


@pytest.mark.asyncio
async def test_list_requires_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/users")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_rejects_non_admin(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/users")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_rejects_non_admin(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/users",
            json={
                "email": "x@x.com",
                "role": "agent",
                "password": "pw-min-8c",
            },
        )
    assert r.status_code == 403


# ----------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_list_returns_payload(app, override_user, patch_service):
    override_user("admin")
    patch_service.list_users = AsyncMock(
        return_value=UserListResponse(items=[_u()], total=1, limit=50, offset=0)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/users?role=agent&q=a")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    # GET must not commit.
    app.state._test_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_commits(app, override_user, patch_service):
    override_user("admin")
    patch_service.create_user = AsyncMock(return_value=_u())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/users",
            json={
                "email": "x@y.com",
                "name": "Z",
                "role": "agent",
                "password": "pw-min-8c",
            },
        )
    assert r.status_code == 201, r.text
    patch_service.create_user.assert_awaited_once()
    app.state._test_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_commits(app, override_user, patch_service):
    override_user("admin")
    patch_service.update_user = AsyncMock(return_value=_u())
    transport = ASGITransport(app=app)
    target = uuid.uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch(
            f"/api/v1/users/{target}", json={"name": "New"}
        )
    assert r.status_code == 200, r.text
    patch_service.update_user.assert_awaited_once()
    app.state._test_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_password_commits_and_returns_204(
    app, override_user, patch_service
):
    override_user("admin")
    patch_service.reset_password = AsyncMock(return_value=None)
    transport = ASGITransport(app=app)
    target = uuid.uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/users/{target}/reset-password",
            json={"password": "newpassword1"},
        )
    assert r.status_code == 204
    patch_service.reset_password.assert_awaited_once()
    app.state._test_session.commit.assert_awaited_once()


# ----------------------------------------------------------- schema rejection


@pytest.mark.asyncio
async def test_patch_unknown_field_422(app, override_user, patch_service):
    override_user("admin")
    transport = ASGITransport(app=app)
    target = uuid.uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.patch(
            f"/api/v1/users/{target}", json={"hacked": True}
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_short_password_422(app, override_user, patch_service):
    override_user("admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/users",
            json={"email": "a@b.com", "role": "agent", "password": "short"},
        )
    assert r.status_code == 422


# ---------------------------------------------------------- section access


@pytest.mark.asyncio
async def test_get_sections_requires_admin(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    target = uuid.uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(f"/api/v1/users/{target}/sections")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_put_sections_requires_admin(app, override_user, patch_service):
    override_user("agent")
    transport = ASGITransport(app=app)
    target = uuid.uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put(
            f"/api/v1/users/{target}/sections",
            json={"sections": ["inbox"]},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_sections_returns_payload(app, override_user, patch_service):
    override_user("admin")
    patch_service.get_user_sections = AsyncMock(
        return_value=UserSectionsResponse(
            sections=["inbox", "contacts", "campaigns", "templates", "tag-review"]
        )
    )
    transport = ASGITransport(app=app)
    target = uuid.uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(f"/api/v1/users/{target}/sections")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "sections" in body
    assert len(body["sections"]) == 5
    # GET must not commit.
    app.state._test_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_put_sections_commits(app, override_user, patch_service):
    override_user("admin")
    patch_service.update_user_sections = AsyncMock(
        return_value=UserSectionsResponse(
            sections=["inbox", "contacts"]
        )
    )
    transport = ASGITransport(app=app)
    target = uuid.uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put(
            f"/api/v1/users/{target}/sections",
            json={"sections": ["inbox", "contacts"]},
        )
    assert r.status_code == 200, r.text
    patch_service.update_user_sections.assert_awaited_once()
    app.state._test_session.commit.assert_awaited_once()
