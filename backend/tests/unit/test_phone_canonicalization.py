"""Phone canonicalization — the fix for inbound replies opening a new chat
with only the number instead of matching the saved contact.

Root cause was a format mismatch: contacts were stored as '+15551234567' (or
other formatted variants) while Meta reports inbound senders as the bare wa_id
'15551234567'. The exact-string lookup missed and a name-less duplicate was
created. canonicalize_phone reduces every ingress point to one digits-only
form so the lookup always hits.
"""

from __future__ import annotations

import pytest

from app.core.phone import canonicalize_phone, format_phone_for_display
from app.modules.contacts.schemas import ContactCreateRequest


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+15551234567", "15551234567"),
        ("15551234567", "15551234567"),       # already canonical
        ("+1 (555) 123-4567", "15551234567"),
        ("1-555-123-4567", "15551234567"),
        ("  +1 555 123 4567  ", "15551234567"),
        ("", ""),
        (None, ""),
    ],
)
def test_canonicalize_phone(raw, expected):
    assert canonicalize_phone(raw) == expected


def test_contact_create_request_stores_canonical_phone():
    """A contact created with a '+'-prefixed/formatted number is stored in the
    bare wa_id form, so Meta's inbound `from` matches it on the first reply."""
    req = ContactCreateRequest(phone="+1 (555) 123-4567", name="Jane")
    assert req.phone == "15551234567"


def test_contact_create_request_rejects_digitless_phone():
    with pytest.raises(ValueError):
        ContactCreateRequest(phone="++--", name="Nope")


# ----------------------------------------------------------------- format_phone_for_display


@pytest.mark.parametrize(
    "raw,expected",
    [
        # UAE mobile
        ("+971501234567", "+971 50 123 4567"),
        ("971501234567", "+971 50 123 4567"),
        ("971 50 123 4567", "+971 50 123 4567"),
        # UAE landline
        ("97143901234", "+971 43 901 234"),
        # US/Canada
        ("15551234567", "+1 555 123 4567"),
        ("+1 (555) 123-4567", "+1 555 123 4567"),
        # India
        ("919876543210", "+91 98765 43210"),
        # Pakistan
        ("923001234567", "+92 300 1234567"),
        # UK
        ("442071234567", "+44 2071 234567"),
        # Saudi Arabia
        ("966501234567", "+966 50 123 4567"),
        # Gulf states
        ("96512345678", "+965 123 4567 8"),
        ("97412345678", "+974 1234 5678"),
        ("97312345678", "+973 1234 5678"),
        ("96812345678", "+968 1234 5678"),
        # Short national — fewer digits than the group pattern expects.
        # The trailing empty group is silently skipped.
        ("97112345", "+971 12 345"),
        ("9651234567", "+965 123 4567"),
        # Fallback — unrecognised country code
        ("8613800000000", "+8613800000000"),
        ("33123456789", "+33123456789"),
        # Empty / None passthrough
        ("", ""),
        (None, ""),
    ],
)
def test_format_phone_for_display(raw, expected):
    assert format_phone_for_display(raw) == expected
