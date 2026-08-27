"""Canonical phone-number normalization and display formatting.

WhatsApp identifies every user by its ``wa_id`` — digits only, no ``+``,
spaces, or punctuation (E.164 without the leading ``+``). Meta's inbound
webhook always reports the sender in this form (``msg.from``).

Every place a phone number ENTERS the system — manual contact create, CSV
import, the inbound webhook — must reduce to this same canonical form before
it is stored or used for lookup. Otherwise the exact-string match in
``ContactRepository.upsert_by_phone(_sync)`` (``Contact.phone == phone``)
fails: a contact saved as ``+15551234567`` never matches an inbound
``15551234567``, so the customer's first reply spawns a brand-new, name-less
duplicate contact and a separate conversation.

Keeping this as one tiny pure function means there is a single source of truth
for "what is the canonical phone string", shared by both the async (HTTP) and
sync (Celery) paths.
"""

from __future__ import annotations

import re

_NON_DIGIT_RE = re.compile(r"[^0-9]")

# Country-specific national-number grouping for display formatting.
# Each value is a list of group sizes applied left-to-right; any remaining
# digits (shorter or longer than expected) are appended as the final group.
# Sorted by key length descending to match longer codes first (e.g. "971"
# before "91", "1").
_FORMAT_RULES: dict[str, list[int]] = {
    "971": [2, 3, 4],   # +971 XX XXX XXXX (UAE mobile: 5X XXX XXXX)
    "966": [2, 3, 4],   # +966 XX XXX XXXX (Saudi Arabia mobile: 5X XXX XXXX)
    "965": [3, 4],      # +965 XXX XXXX (Kuwait)
    "974": [4, 4],      # +974 XXXX XXXX (Qatar)
    "973": [4, 4],      # +973 XXXX XXXX (Bahrain)
    "968": [4, 4],      # +968 XXXX XXXX (Oman)
    "1":   [3, 3, 4],   # +1 XXX XXX XXXX (US/Canada)
    "44":  [4, 6],      # +44 XXXX XXXXXX (UK)
    "91":  [5, 5],      # +91 XXXXX XXXXX (India)
    "92":  [3, 7],      # +92 XXX XXXXXXX (Pakistan)
}


def canonicalize_phone(raw: str | None) -> str:
    """Reduce a phone number to digits only, matching Meta's ``wa_id`` form.

    Strips ``+``, spaces, hyphens, parentheses, and any other non-digit
    character. ``None``/empty input yields an empty string (callers that
    require a value should validate the result is non-empty).

    Examples:
        ``+1 (555) 123-4567`` -> ``15551234567``
        ``15551234567``       -> ``15551234567``  (already canonical)
    """
    return _NON_DIGIT_RE.sub("", raw or "")


def format_phone_for_display(raw: str | None) -> str:
    """Format a phone number for display with proper international spacing.

    Accepts any phone form (canonical digits-only, already-formatted, or
    messy input), canonicalizes it, then applies country-specific grouping
    so the receiver can read and message the number directly.

    Falls back to ``+<digits>`` when the country code is not in the
    recognised set.

    Examples:
        ``+971501234567``  -> ``+971 50 123 4567``
        ``971501234567``   -> ``+971 50 123 4567``
        ``15551234567``    -> ``+1 555 123 4567``
    """
    canonical = canonicalize_phone(raw)
    if not canonical:
        return raw or ""

    # Longest-match first (sorted above) so e.g. "971" beats "91" for UAE.
    for cc in sorted(_FORMAT_RULES, key=len, reverse=True):
        if canonical.startswith(cc):
            national = canonical[len(cc):]
            groups = _FORMAT_RULES[cc]
            parts = [f"+{cc}"]
            idx = 0
            for g in groups:
                chunk = national[idx:idx + g]
                if chunk:
                    parts.append(chunk)
                idx += g
            if idx < len(national):
                parts.append(national[idx:])
            return " ".join(parts)

    return f"+{canonical}"
