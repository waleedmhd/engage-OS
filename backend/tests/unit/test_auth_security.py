"""Unit tests for app.core.security primitives.

Production API:
  * create_access_token(subject, role, extra_claims=None)
  * decode_access_token(token) -> dict
  * hash_refresh_token(raw) -> 64-char hex
  * generate_refresh_token() -> str
  * refresh_token_expires_at(now=None) -> datetime
  * hash_password(plain) / verify_password(plain, hashed)
  * Auth-I1: reserved claims (sub/iat/exp/jti) cannot be overwritten via extra_claims
"""
from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from jose import jwt

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expires_at,
    verify_password,
)

# ---- password hashing ----

def test_hash_password_produces_bcrypt_hash():
    hashed = hash_password("hunter2")
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")


def test_verify_password_correct():
    hashed = hash_password("correct-horse")
    assert verify_password("correct-horse", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("correct-horse")
    assert verify_password("wrong-horse", hashed) is False


def test_hash_password_different_each_call():
    assert hash_password("same") != hash_password("same")


# ---- access token ----

def test_create_access_token_decodes():
    settings = get_settings()
    token = create_access_token(subject="user-123", role="agent")
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "user-123"
    assert payload["role"] == "agent"


def test_access_token_includes_extra_claims():
    settings = get_settings()
    token = create_access_token(
        subject="u1", role="admin", extra_claims={"email": "a@b.com"}
    )
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert payload["email"] == "a@b.com"


def test_access_token_has_future_expiry():
    token = create_access_token(subject="u1", role="agent")
    claims = decode_access_token(token)
    assert claims["exp"] > int(time.time())


def test_decode_access_token_returns_claims():
    token = create_access_token(subject="u1", role="agent")
    claims = decode_access_token(token)
    assert claims["sub"] == "u1"
    assert "exp" in claims
    assert "iat" in claims
    assert "jti" in claims


def test_decode_access_token_raises_on_bad_token():
    with pytest.raises(AuthenticationError):
        decode_access_token("not.a.token")


# ---- Auth-I1: reserved claim hardening ----

@pytest.mark.parametrize("reserved", ["sub", "iat", "exp", "jti"])
def test_extra_claims_cannot_overwrite_reserved(reserved):
    """Auth-I1 regression: passing a reserved key in extra_claims must raise."""
    with pytest.raises(ValueError, match="reserved JWT claim"):
        create_access_token(subject="u1", role="agent", extra_claims={reserved: "evil"})


def test_extra_claims_cannot_replace_subject_silently():
    """Even after the validator fires, the issued token's `sub` must be the
    one passed positionally — never the one from extra_claims."""
    # This call raises (validated above). What we verify here: a benign
    # custom claim is preserved, and the subject is the positional arg.
    token = create_access_token(
        subject="legitimate-user", role="agent", extra_claims={"custom": "ok"}
    )
    claims = decode_access_token(token)
    assert claims["sub"] == "legitimate-user"
    assert claims["custom"] == "ok"


# ---- refresh token helpers ----

def test_generate_refresh_token_is_url_safe_string():
    token = generate_refresh_token()
    assert isinstance(token, str)
    assert len(token) >= 40


def test_generate_refresh_token_unique():
    assert generate_refresh_token() != generate_refresh_token()


def test_hash_refresh_token_is_64_hex_chars():
    h = hash_refresh_token("some-token")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_refresh_token_deterministic():
    assert hash_refresh_token("abc") == hash_refresh_token("abc")


def test_hash_refresh_token_different_for_different_input():
    assert hash_refresh_token("a") != hash_refresh_token("b")


def test_refresh_token_expires_at_is_tz_aware_and_in_future():
    settings = get_settings()
    expires = refresh_token_expires_at()
    assert expires.tzinfo is not None
    delta = expires - datetime.now(UTC)
    # Should be approximately REFRESH_TOKEN_EXPIRE_DAYS days.
    assert delta.days >= settings.REFRESH_TOKEN_EXPIRE_DAYS - 1
    assert delta.days <= settings.REFRESH_TOKEN_EXPIRE_DAYS + 1


def test_refresh_token_expires_at_accepts_anchor():
    """Caller can pin the `now` reference, useful for deterministic tests."""
    anchor = datetime(2026, 1, 1, tzinfo=UTC)
    expires = refresh_token_expires_at(now=anchor)
    settings = get_settings()
    assert (expires - anchor).days == settings.REFRESH_TOKEN_EXPIRE_DAYS
