"""Unit tests for AuthService.

Phase 4.5 fixes covered:
- Auth-C1: refresh-token persistence requires the router to commit (service flushes only)
- Auth-I3: token expiry uses .astimezone(utc), not .replace(tzinfo=utc)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AuthenticationError
from app.modules.auth.service import AuthService


def _make_user(*, role: str = "agent", is_active: bool = True) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = "user@example.com"
    u.role = role
    u.is_active = is_active
    u.hashed_password = "$2b$12$dummyhash"
    return u


def _make_service() -> AuthService:
    """Build an AuthService with all repos replaced by AsyncMocks."""
    session = AsyncMock()
    svc = AuthService(session)
    svc._repo = AsyncMock()
    svc._token_repo = AsyncMock()
    return svc


# ----------------------------------------------------------- login

@pytest.mark.asyncio
async def test_login_success_creates_refresh_token(monkeypatch):
    """Auth-C1 setup: login() must call _token_repo.create so the router can commit."""
    monkeypatch.setattr(
        "app.modules.auth.service.verify_password", lambda *_: True
    )
    svc = _make_service()
    user = _make_user()
    svc._repo.get_user_by_email.return_value = user

    result = await svc.login(email="user@example.com", password="x")

    svc._token_repo.create.assert_awaited_once()
    kw = svc._token_repo.create.await_args.kwargs
    assert kw["user_id"] == user.id
    assert "token_hash" in kw
    assert kw["expires_at"].tzinfo is not None  # tz-aware
    assert result.access_token
    assert result.refresh_token
    assert result.token_type == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(monkeypatch):
    monkeypatch.setattr(
        "app.modules.auth.service.verify_password", lambda *_: False
    )
    svc = _make_service()
    svc._repo.get_user_by_email.return_value = _make_user()

    with pytest.raises(AuthenticationError):
        await svc.login(email="user@example.com", password="wrong")

    svc._token_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_unknown_email():
    svc = _make_service()
    svc._repo.get_user_by_email.return_value = None

    with pytest.raises(AuthenticationError):
        await svc.login(email="ghost@example.com", password="any")

    svc._token_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_inactive_user(monkeypatch):
    monkeypatch.setattr(
        "app.modules.auth.service.verify_password", lambda *_: True
    )
    svc = _make_service()
    svc._repo.get_user_by_email.return_value = _make_user(is_active=False)

    with pytest.raises(AuthenticationError):
        await svc.login(email="user@example.com", password="x")


# ----------------------------------------------------------- Auth-C1 rotation

@pytest.mark.asyncio
async def test_refresh_revokes_old_and_creates_new():
    """Auth-C1: refresh() revokes the old token AND creates a new one in
    the same session, so the router can commit both atomically."""
    svc = _make_service()
    user = _make_user()

    record = MagicMock()
    record.id = uuid.uuid4()
    record.user_id = user.id
    record.revoked = False
    record.expires_at = datetime.now(tz=UTC) + timedelta(days=7)

    svc._token_repo.get_by_hash.return_value = record
    svc._repo.get_user_by_id.return_value = user

    result = await svc.refresh(token="some-raw-token")

    svc._token_repo.revoke.assert_awaited_once_with(record.id)
    svc._token_repo.create.assert_awaited_once()
    new_create_kw = svc._token_repo.create.await_args.kwargs
    assert new_create_kw["user_id"] == user.id
    assert result.refresh_token != "some-raw-token"


@pytest.mark.asyncio
async def test_refresh_with_revoked_record_raises():
    svc = _make_service()
    record = MagicMock()
    record.revoked = True
    svc._token_repo.get_by_hash.return_value = record

    with pytest.raises(AuthenticationError):
        await svc.refresh(token="x")
    svc._token_repo.create.assert_not_awaited()


# ----------------------------------------------------------- Auth-I3

@pytest.mark.asyncio
async def test_refresh_expiry_uses_astimezone_for_non_utc_offsets():
    """Auth-I3: when the DB returns a tz-aware datetime in a non-UTC
    timezone, .astimezone(utc) converts the instant correctly. The buggy
    .replace(tzinfo=utc) would shift the instant by the offset.

    Setup: build expires_at as a UTC instant 4h in the past, expressed in
    UTC+04:00 — naive `.replace(tzinfo=utc)` would interpret this as 4h in
    the *future*, masking the expiry. Correct `.astimezone(utc)` sees it
    as expired.
    """
    svc = _make_service()
    user = _make_user()

    # Build an expiry whose wall-clock fields are 1h after "now in UTC", but
    # labeled as +04:00. As an absolute instant this is 3h in the PAST UTC.
    #
    # Buggy .replace(tzinfo=utc) keeps wall-clock fields → instant looks 1h
    # in the future (NOT expired).
    # Correct .astimezone(utc) converts the +04:00 instant to UTC → 3h in
    # the past (EXPIRED).
    plus_four = timezone(timedelta(hours=4))
    future_in_utc = datetime.now(tz=UTC) + timedelta(hours=1)
    record_expires_at = future_in_utc.replace(tzinfo=plus_four)
    # Sanity: actual instant is 3h in the past UTC.
    assert record_expires_at.astimezone(UTC) < datetime.now(tz=UTC)
    # Sanity: under buggy .replace(tzinfo=utc) it would look 1h in the future.
    assert record_expires_at.replace(tzinfo=UTC) > datetime.now(tz=UTC)

    record = MagicMock()
    record.id = uuid.uuid4()
    record.user_id = user.id
    record.revoked = False
    record.expires_at = record_expires_at
    svc._token_repo.get_by_hash.return_value = record
    svc._repo.get_user_by_id.return_value = user

    # Under the correct .astimezone(utc), this token is expired and should raise.
    with pytest.raises(AuthenticationError, match="expired"):
        await svc.refresh(token="raw")


@pytest.mark.asyncio
async def test_refresh_with_future_expiry_in_non_utc_offset_succeeds():
    """Sanity for Auth-I3: a token genuinely 4h in the future, expressed in
    UTC+04:00, must NOT be treated as expired."""
    svc = _make_service()
    user = _make_user()

    plus_four = timezone(timedelta(hours=4))
    future_utc_instant = datetime.now(tz=UTC) + timedelta(hours=4)
    record_expires_at = future_utc_instant.astimezone(plus_four)

    record = MagicMock()
    record.id = uuid.uuid4()
    record.user_id = user.id
    record.revoked = False
    record.expires_at = record_expires_at
    svc._token_repo.get_by_hash.return_value = record
    svc._repo.get_user_by_id.return_value = user

    result = await svc.refresh(token="raw")
    assert result.access_token
