"""Integration-style tests for auth endpoints using the ASGI test client.

Repositories are patched so no real Postgres is needed. Targets the post-
Phase-4.5 production API: ``AuthService(session)``, ``AuthenticationError``
(code ``authentication_error``, HTTP 401), TZ-aware refresh expiries.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token, hash_password, hash_refresh_token
from app.modules.auth.models import RefreshToken, User


# ---------------------------------------------------------------- helpers
def _active_user(role: str = "agent") -> User:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = "user@example.com"
    u.name = "Test"
    u.role = role
    u.is_active = True
    u.hashed_password = hash_password("password123")
    return u


def _refresh_record(user_id: uuid.UUID, raw_token: str) -> RefreshToken:
    """Auth-I3 regression: expiries MUST be timezone-aware (asyncpg returns
    aware datetimes from TIMESTAMPTZ; AuthService normalises via .astimezone).
    The previous test fixture stripped tzinfo, which masked the bug."""
    r = MagicMock(spec=RefreshToken)
    r.id = uuid.uuid4()
    r.user_id = user_id
    r.token_hash = hash_refresh_token(raw_token)
    r.revoked = False
    r.expires_at = datetime.now(UTC) + timedelta(days=30)
    return r


# ---------------------------------------------------------------- /auth/login
@pytest.mark.asyncio
async def test_login_returns_tokens(client):
    user = _active_user()
    with (
        patch("app.modules.auth.service.AuthRepository") as MockAuthRepo,
        patch("app.modules.auth.service.RefreshTokenRepository") as MockRefreshRepo,
    ):
        MockAuthRepo.return_value.get_user_by_email = AsyncMock(return_value=user)
        MockRefreshRepo.return_value.create = AsyncMock(return_value=MagicMock())

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "password123"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client):
    user = _active_user()
    with (
        patch("app.modules.auth.service.AuthRepository") as MockAuthRepo,
        patch("app.modules.auth.service.RefreshTokenRepository"),
    ):
        MockAuthRepo.return_value.get_user_by_email = AsyncMock(return_value=user)

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "wrong"},
        )

    assert response.status_code == 401
    body = response.json()
    # AuthenticationError → code "authentication_error" (subclass of AuthError)
    assert body["error"]["code"] in ("authentication_error", "auth_error")


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401(client):
    with (
        patch("app.modules.auth.service.AuthRepository") as MockAuthRepo,
        patch("app.modules.auth.service.RefreshTokenRepository"),
    ):
        MockAuthRepo.return_value.get_user_by_email = AsyncMock(return_value=None)

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "pw"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_account_returns_401(client):
    user = _active_user()
    user.is_active = False
    with (
        patch("app.modules.auth.service.AuthRepository") as MockAuthRepo,
        patch("app.modules.auth.service.RefreshTokenRepository"),
    ):
        MockAuthRepo.return_value.get_user_by_email = AsyncMock(return_value=user)

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "password123"},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------- /auth/refresh
@pytest.mark.asyncio
async def test_refresh_returns_new_tokens(client):
    user = _active_user()
    plain = "valid-opaque-refresh-token"
    record = _refresh_record(user.id, plain)

    with (
        patch("app.modules.auth.service.AuthRepository") as MockAuthRepo,
        patch("app.modules.auth.service.RefreshTokenRepository") as MockRefreshRepo,
    ):
        MockAuthRepo.return_value.get_user_by_id = AsyncMock(return_value=user)
        MockRefreshRepo.return_value.get_by_hash = AsyncMock(return_value=record)
        MockRefreshRepo.return_value.revoke = AsyncMock(return_value=None)
        MockRefreshRepo.return_value.create = AsyncMock(return_value=MagicMock())

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": plain},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    # Rotation: the returned token MUST differ from the consumed one.
    assert body["refresh_token"] != plain


@pytest.mark.asyncio
async def test_refresh_invalid_token_returns_401(client):
    with (
        patch("app.modules.auth.service.AuthRepository"),
        patch("app.modules.auth.service.RefreshTokenRepository") as MockRefreshRepo,
    ):
        MockRefreshRepo.return_value.get_by_hash = AsyncMock(return_value=None)

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "garbage"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_revoked_token_returns_401(client):
    user = _active_user()
    plain = "revoked-token"
    record = _refresh_record(user.id, plain)
    record.revoked = True

    with (
        patch("app.modules.auth.service.AuthRepository"),
        patch("app.modules.auth.service.RefreshTokenRepository") as MockRefreshRepo,
    ):
        MockRefreshRepo.return_value.get_by_hash = AsyncMock(return_value=record)

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": plain},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_expired_token_returns_401(client):
    """Auth-I3 regression: aware expiry in the past must be detected."""
    user = _active_user()
    plain = "expired-token"
    record = _refresh_record(user.id, plain)
    record.expires_at = datetime.now(UTC) - timedelta(hours=1)

    with (
        patch("app.modules.auth.service.AuthRepository"),
        patch("app.modules.auth.service.RefreshTokenRepository") as MockRefreshRepo,
    ):
        MockRefreshRepo.return_value.get_by_hash = AsyncMock(return_value=record)

        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": plain},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------- /auth/me
@pytest.mark.asyncio
async def test_me_returns_current_user(app):
    from app.core.dependencies import get_current_user_db

    user = _active_user(role="admin")
    token = create_access_token(subject=str(user.id), role=user.role)

    app.dependency_overrides[get_current_user_db] = lambda: user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == user.email
    assert body["role"] == "admin"
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_me_no_token_returns_401(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_bad_token_returns_401(client):
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not.a.valid.token"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------- require_role
@pytest.mark.asyncio
async def test_require_role_allows_matching_role():
    from app.core.dependencies import require_role

    checker = require_role("admin")
    claims = {"sub": "u1", "role": "admin"}
    result = await checker(claims)
    assert result == claims


@pytest.mark.asyncio
async def test_require_role_rejects_wrong_role():
    from app.core.dependencies import require_role
    from app.core.exceptions import ForbiddenError

    checker = require_role("admin")
    claims = {"sub": "u1", "role": "agent"}
    with pytest.raises(ForbiddenError):
        await checker(claims)


@pytest.mark.asyncio
async def test_require_role_allows_any_of_multiple():
    from app.core.dependencies import require_role

    checker = require_role("admin", "agent")
    claims = {"sub": "u1", "role": "agent"}
    result = await checker(claims)
    assert result["role"] == "agent"
