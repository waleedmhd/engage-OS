"""Unit tests for the small id/time helpers."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.utils.ids import is_uuid, new_uuid
from app.utils.time import to_iso, utcnow


def test_new_uuid_is_uuid():
    u = new_uuid()
    assert isinstance(u, uuid.UUID)


def test_is_uuid_true_and_false():
    assert is_uuid(str(uuid.uuid4())) is True
    assert is_uuid("not-a-uuid") is False
    assert is_uuid(None) is False  # type: ignore[arg-type]


def test_utcnow_is_tz_aware_utc():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == UTC.utcoffset(None)


def test_to_iso_coerces_naive_to_utc():
    naive = datetime(2026, 5, 16, 12, 0, 0)
    aware = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    assert to_iso(naive).endswith("+00:00")
    assert to_iso(aware) == aware.isoformat()
