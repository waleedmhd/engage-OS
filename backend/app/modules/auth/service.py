"""
app/modules/auth/service.py

Fix applied:
  Auth-I3 — record.expires_at.replace(tzinfo=timezone.utc) was used to
             attach UTC timezone info to the expiry datetime before comparing
             it to datetime.now(tz=timezone.utc).

             The problem: asyncpg returns timezone-AWARE datetimes from
             TIMESTAMPTZ columns. Calling .replace(tzinfo=...) on an already-
             aware datetime REPLACES the stored timezone info with the new one
             rather than converting to it. If asyncpg returns UTC+4 (e.g. from
             a server with a local timezone set), .replace(tzinfo=utc) strips
             the +4 offset and reinterprets the timestamp as UTC, effectively
             adding 4 hours to the actual expiry instant. Tokens would appear
             valid up to 4 hours after they had actually expired.

             Fix: use .astimezone(timezone.utc) which CONVERTS an aware
             datetime to UTC without changing the instant it represents.
             This is the correct operation for normalising a known-aware
             datetime to a reference timezone for comparison.

             Note: tests previously masked this bug by stripping tzinfo in
             fixtures (creating naive datetimes that behave identically under
             both .replace() and .astimezone()). Tests must use aware fixtures.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_password,
)
from app.modules.auth.repository import AuthRepository, RefreshTokenRepository
from app.modules.auth.schemas import LoginResponse, RefreshResponse

if TYPE_CHECKING:
    from app.modules.auth.models import User


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = AuthRepository(session)
        self._token_repo = RefreshTokenRepository(session)
        self._settings = get_settings()

    async def login(self, email: str, password: str) -> LoginResponse:
        """
        Validate credentials and issue token pair.

        Caller (router) is responsible for committing the session so the
        RefreshToken row is durably persisted. This service only flushes.
        """
        user = await self._repo.get_user_by_email(email.lower())

        if user is None or not verify_password(password, user.hashed_password):
            # Return a generic message to prevent user enumeration.
            raise AuthenticationError("Invalid credentials.")

        if not user.is_active:
            raise AuthenticationError("Account is deactivated.")

        access_token = create_access_token(
            subject=str(user.id),
            role=user.role,
        )
        raw_refresh = generate_refresh_token()

        await self._token_repo.create(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=datetime.now(tz=UTC)
            + timedelta(days=self._settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )

        return LoginResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            token_type="bearer",
        )

    async def refresh(self, token: str) -> RefreshResponse:
        """
        Validate a refresh token, rotate it, and return a new token pair.

        Caller (router) is responsible for committing the session so the
        revocation and new token creation are durably written atomically.
        """
        token_hash = hash_refresh_token(token)
        record = await self._token_repo.get_by_hash(token_hash)

        if record is None or record.revoked:
            raise AuthenticationError("Invalid or revoked refresh token.")

        # Auth-I3 fix: use .astimezone(utc) not .replace(tzinfo=utc).
        #
        # asyncpg returns TIMESTAMPTZ columns as timezone-aware datetimes.
        # .replace(tzinfo=utc) reinterprets the stored bytes as UTC without
        # converting — if the server has a non-UTC local timezone, the
        # effective instant shifts, making token expiry incorrect.
        #
        # .astimezone(utc) converts the aware datetime to UTC correctly,
        # preserving the actual point in time the expiry represents.
        expires_at_utc = record.expires_at.astimezone(UTC)

        if datetime.now(tz=UTC) >= expires_at_utc:
            raise AuthenticationError("Refresh token has expired.")

        user = await self._repo.get_user_by_id(record.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Associated user not found or inactive.")

        # Rotate: revoke the consumed token, issue a new one.
        await self._token_repo.revoke(record.id)

        new_raw = generate_refresh_token()
        await self._token_repo.create(
            user_id=user.id,
            token_hash=hash_refresh_token(new_raw),
            expires_at=datetime.now(tz=UTC)
            + timedelta(days=self._settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )

        new_access = create_access_token(
            subject=str(user.id),
            role=user.role,
        )

        return RefreshResponse(
            access_token=new_access,
            refresh_token=new_raw,
            token_type="bearer",
        )

    async def revoke_token(self, token: str) -> None:
        """Revoke a refresh token. No-op if already revoked or not found."""
        token_hash = hash_refresh_token(token)
        record = await self._token_repo.get_by_hash(token_hash)
        if record is not None and not record.revoked:
            await self._token_repo.revoke(record.id)

    async def get_user_by_id(self, user_id: uuid.UUID) -> User:
        user = await self._repo.get_user_by_id(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user
