"""Static webhook + AI response fixtures used by integration and E2E tests.

Each helper loads a JSON file relative to this package and returns the parsed
payload. `signed_meta_payload(name, secret)` returns a tuple
(raw_bytes, signature_header) for tests that exercise HMAC signature verification.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def load_payload(name: str) -> dict:
    """Load and parse a JSON payload by base name (without .json)."""
    return json.loads((_DIR / f"{name}.json").read_text(encoding="utf-8"))


def load_payload_bytes(name: str) -> bytes:
    """Load raw bytes of a JSON payload (preserving exact byte sequence for HMAC)."""
    return (_DIR / f"{name}.json").read_bytes()


def sign_meta(raw_body: bytes, app_secret: str) -> str:
    """Produce the `X-Hub-Signature-256` header value for a given raw body."""
    digest = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def signed_meta_payload(name: str, app_secret: str) -> tuple[bytes, str]:
    body = load_payload_bytes(name)
    return body, sign_meta(body, app_secret)
