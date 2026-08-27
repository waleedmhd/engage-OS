"""HMAC-SHA256 verification — DSD §9 webhook security."""

from app.integrations.meta.signature import sign_payload, verify_meta_signature

SECRET = "topsecret"
BODY = b'{"hello":"world"}'


def test_round_trip_accepts_matching_signature() -> None:
    header = sign_payload(BODY, SECRET)
    assert verify_meta_signature(BODY, header, SECRET) is True


def test_rejects_mismatched_secret() -> None:
    header = sign_payload(BODY, SECRET)
    assert verify_meta_signature(BODY, header, "different-secret") is False


def test_rejects_mismatched_body() -> None:
    header = sign_payload(BODY, SECRET)
    assert verify_meta_signature(b'{"x":1}', header, SECRET) is False


def test_rejects_missing_header() -> None:
    assert verify_meta_signature(BODY, None, SECRET) is False
    assert verify_meta_signature(BODY, "", SECRET) is False


def test_rejects_wrong_prefix() -> None:
    assert verify_meta_signature(BODY, "sha1=deadbeef", SECRET) is False


def test_rejects_empty_hex_after_prefix() -> None:
    assert verify_meta_signature(BODY, "sha256=", SECRET) is False


def test_rejects_when_app_secret_blank() -> None:
    header = sign_payload(BODY, SECRET)
    assert verify_meta_signature(BODY, header, "") is False
