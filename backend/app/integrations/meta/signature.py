"""Meta webhook signature verification (HMAC-SHA256).

Meta signs every webhook with `X-Hub-Signature-256: sha256=<hex>` using the
app secret as the HMAC key over the raw request body. Constant-time
comparison; never raises — returns False on any malformed input.
"""

from __future__ import annotations

import hashlib
import hmac

_PREFIX = "sha256="


def verify_meta_signature(
    raw_body: bytes,
    signature_header: str | None,
    app_secret: str,
) -> bool:
    if not signature_header or not app_secret:
        return False
    if not signature_header.startswith(_PREFIX):
        return False
    expected_hex = signature_header[len(_PREFIX):].strip().lower()
    if not expected_hex:
        return False
    digest = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_hex, digest)


def sign_payload(raw_body: bytes, app_secret: str) -> str:
    """Helper for tests — produce the header value Meta would send."""
    digest = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"{_PREFIX}{digest}"
