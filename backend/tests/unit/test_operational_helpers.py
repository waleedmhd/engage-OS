"""Pure operational config + timezone-math helpers (no DB/Redis)."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from app.modules.settings.operational import (
    BusinessHours,
    DailyCap,
    OperationalConfig,
    daily_counter_key,
    is_within_business_hours,
    seconds_until_local_midnight,
    seconds_until_window_open,
)

DUBAI = ZoneInfo("Asia/Dubai")  # UTC+4, no DST


def _cfg(*, bh_enabled=True, start="09:00", end="18:00",
         cap_enabled=True, limit=800) -> OperationalConfig:
    sh, eh = (int(start[:2]), int(start[3:])), (int(end[:2]), int(end[3:]))
    return OperationalConfig(
        tz=DUBAI,
        business_hours=BusinessHours(
            enabled=bh_enabled, start=time(*sh), end=time(*eh)
        ),
        cap=DailyCap(enabled=cap_enabled, limit=limit),
    )


def test_within_hours_true_midwindow():
    # 12:00 Dubai == 08:00 UTC
    now = datetime(2026, 5, 20, 8, 0, tzinfo=UTC)
    assert is_within_business_hours(_cfg(), now) is True


def test_within_hours_false_before_open():
    # 06:00 Dubai == 02:00 UTC, window opens 09:00 Dubai
    now = datetime(2026, 5, 20, 2, 0, tzinfo=UTC)
    assert is_within_business_hours(_cfg(), now) is False


def test_within_hours_false_at_end_exclusive():
    # 18:00 Dubai == 14:00 UTC, end is exclusive
    now = datetime(2026, 5, 20, 14, 0, tzinfo=UTC)
    assert is_within_business_hours(_cfg(), now) is False


def test_within_hours_disabled_always_true():
    now = datetime(2026, 5, 20, 23, 0, tzinfo=UTC)
    assert is_within_business_hours(_cfg(bh_enabled=False), now) is True


def test_seconds_until_window_open_same_day():
    # 06:00 Dubai, opens 09:00 Dubai -> 3h = 10800s
    now = datetime(2026, 5, 20, 2, 0, tzinfo=UTC)
    assert seconds_until_window_open(_cfg(), now) == 3 * 3600


def test_seconds_until_window_open_next_day():
    # 20:00 Dubai (after close) -> next open 09:00 next day = 13h
    now = datetime(2026, 5, 20, 16, 0, tzinfo=UTC)
    assert seconds_until_window_open(_cfg(), now) == 13 * 3600


def test_seconds_until_local_midnight():
    # 22:00 Dubai == 18:00 UTC -> 2h to local midnight
    now = datetime(2026, 5, 20, 18, 0, tzinfo=UTC)
    assert seconds_until_local_midnight(_cfg(), now) == 2 * 3600


def test_daily_counter_key_uses_local_date():
    # 22:00 UTC == 02:00 NEXT day Dubai -> key is the Dubai date
    now = datetime(2026, 5, 20, 22, 0, tzinfo=UTC)
    assert daily_counter_key(_cfg(), now) == "campaign:daily_sent:2026-05-21"
