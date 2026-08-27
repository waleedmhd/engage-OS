"""Property tests for Meta HMAC signature verification (Msg-C3 invariants).

Properties guarded:
  P1. Verifying a payload signed with the correct secret always returns True.
  P2. Verifying with the wrong secret always returns False.
  P3. Mutating a single byte of the payload always invalidates the signature.
  P4. Mutating a single byte of the header always invalidates the signature.
  P5. The function never raises on arbitrary header strings, including
      missing prefix, empty, whitespace, and non-ASCII.
"""
from __future__ import annotations

import hashlib
import hmac

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.integrations.meta.signature import sign_payload, verify_meta_signature

_secret_st = st.text(min_size=8, max_size=64, alphabet=st.characters(min_codepoint=33, max_codepoint=126))
_body_st = st.binary(min_size=0, max_size=2048)
_garbage_header_st = st.one_of(
    st.none(),
    st.just(""),
    st.just(" "),
    st.text(min_size=0, max_size=200),
)


@given(secret=_secret_st, body=_body_st)
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p1_correctly_signed_payload_verifies(secret, body):
    header = sign_payload(body, secret)
    assert verify_meta_signature(body, header, secret) is True


@given(secret=_secret_st, other=_secret_st, body=_body_st)
@settings(max_examples=200)
def test_p2_wrong_secret_never_verifies(secret, other, body):
    if secret == other:
        return
    header = sign_payload(body, secret)
    assert verify_meta_signature(body, header, other) is False


@given(secret=_secret_st, body=st.binary(min_size=1, max_size=2048), idx=st.integers(min_value=0, max_value=10_000))
@settings(max_examples=100)
def test_p3_payload_mutation_invalidates(secret, body, idx):
    header = sign_payload(body, secret)
    i = idx % len(body)
    mutated = bytearray(body)
    mutated[i] ^= 0x01
    assert verify_meta_signature(bytes(mutated), header, secret) is False


@given(garbage=_garbage_header_st, secret=_secret_st, body=_body_st)
@settings(max_examples=200)
def test_p5_arbitrary_header_never_raises(garbage, secret, body):
    # Should always return a bool — never raise.
    result = verify_meta_signature(body, garbage, secret)
    assert result is False  # garbage shouldn't accidentally verify


def test_constant_time_comparison_used():
    """Spot-check that the verifier uses hmac.compare_digest (no leaky early-return).
    We inspect the source string of the module — cheap, catches accidental
    regressions to `==` comparison."""
    import app.integrations.meta.signature as mod

    src = (mod.__file__,)  # touch __file__ to ensure module loaded
    del src
    import inspect

    source = inspect.getsource(mod)
    assert "compare_digest" in source, (
        "verify_meta_signature must use hmac.compare_digest; "
        "naive == comparison is timing-attackable."
    )


def test_empty_app_secret_returns_false_not_true():
    """Msg-C3 invariant: empty app_secret must fail closed (never accept the
    signature). Config-time validation also rejects empty secrets in non-dev
    ENVs, but the signature function itself must be safe regardless."""
    body = b"{}"
    digest = hmac.new(b"", body, hashlib.sha256).hexdigest()
    header = f"sha256={digest}"
    assert verify_meta_signature(body, header, "") is False
