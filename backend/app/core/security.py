"""
app/core/security.py

Fix applied:
  Auth-I1 — extra_claims were applied AFTER reserved claims (sub/iat/exp/jti)
             in the original code, meaning a caller could silently overwrite
             them. e.g. create_access_token(..., extra_claims={"sub": "other"})
             would produce a token with the wrong subject.

             Fix: reserved claims are always applied LAST and are immutable.
             Callers passing reserved keys receive an explicit ValueError.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError

# Claims that are always controlled by this module and must not be
# supplied by callers via extra_claims.
_RESERVED_CLAIMS: frozenset[str] = frozenset({"sub", "iat", "exp", "jti"})


def create_access_token(
    subject: str,
    role: str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Issue a signed JWT access token.

    Auth-I1 fix: extra_claims are merged into the payload BEFORE the
    reserved claims are written. Reserved claims are then applied last so
    they cannot be overwritten by callers, either accidentally or
    maliciously. An explicit ValueError is raised if a caller passes a
    reserved key so the mistake is visible rather than silently ignored.

    Args:
        subject:      User UUID as string — becomes the `sub` claim.
        role:         User role string — carried as a custom `role` claim.
        extra_claims: Optional additional claims. Must not contain reserved
                      keys: sub, iat, exp, jti.

    Returns:
        Signed JWT string.

    Raises:
        ValueError: if extra_claims contains a reserved claim key.
    """
    settings = get_settings()

    if extra_claims:
        collisions = _RESERVED_CLAIMS & extra_claims.keys()
        if collisions:
            raise ValueError(
                f"extra_claims must not contain reserved JWT claim keys: "
                f"{sorted(collisions)}. These are always set by create_access_token."
            )

    now = datetime.now(tz=UTC)

    # Start with caller-supplied claims (none of which are reserved — validated above).
    payload: dict[str, Any] = dict(extra_claims) if extra_claims else {}

    # Role is a non-reserved custom claim; always present.
    payload["role"] = role

    # Reserved claims are written last — they cannot be overwritten.
    payload.update(
        {
            "sub": subject,
            "iat": now,
            "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            "jti": secrets.token_hex(16),
        }
    )

    return jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str, settings: Any | None = None) -> dict[str, Any]:
    """
    Decode and verify a JWT access token.

    The optional ``settings`` argument is accepted so callers (including
    ``app.core.dependencies.get_current_user_claims``) can inject a Settings
    instance for testability without forcing a global ``get_settings()`` lookup.

    Raises:
        AuthenticationError: if the token is invalid, expired, or tampered.
    """
    if settings is None:
        settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise AuthenticationError("Invalid or expired access token") from exc


def hash_refresh_token(raw_token: str) -> str:
    """
    Return the hex-encoded SHA-256 digest of a raw refresh token.

    Only the hash is stored in the database — the raw token is never
    persisted. String(64) in the DB model is correct for this format
    (32 bytes → 64 hex characters).
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> str:
    """
    Generate a cryptographically secure URL-safe refresh token.
    The returned string has ~384 bits of entropy (64 URL-safe base64 chars).
    """
    return secrets.token_urlsafe(64)


def refresh_token_expires_at(now: datetime | None = None) -> datetime:
    """Return the UTC-aware expiry timestamp for a freshly-issued refresh token.

    Uses ``REFRESH_TOKEN_EXPIRE_DAYS`` from settings. Exposed as a separate
    helper so the same TTL is consistently applied by both ``AuthService`` and
    tests (and so ``test_auth_security.py`` has a stable import target).
    """
    settings = get_settings()
    base = now if now is not None else datetime.now(tz=UTC)
    return base + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


def hash_password(plain: str) -> str:
    import bcrypt
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    import bcrypt
    return bcrypt.checkpw(plain.encode(), hashed.encode())
