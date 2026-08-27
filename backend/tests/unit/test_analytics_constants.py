"""Pure-logic tests for analytics range resolution."""

from __future__ import annotations

from datetime import date

from app.modules.analytics.constants import AnalyticsRange, resolve_range


def test_resolve_range_day_collapses_to_yesterday():
    today = date(2026, 5, 13)
    start, end = resolve_range(AnalyticsRange.DAY, today=today)
    assert start == date(2026, 5, 12)
    assert end == date(2026, 5, 12)


def test_resolve_range_week_is_seven_days_ending_yesterday():
    today = date(2026, 5, 13)
    start, end = resolve_range(AnalyticsRange.WEEK, today=today)
    assert end == date(2026, 5, 12)
    # Inclusive: 12, 11, 10, 9, 8, 7, 6 → 7 days, start = 6th.
    assert start == date(2026, 5, 6)


def test_resolve_range_month_is_thirty_days():
    today = date(2026, 5, 13)
    start, end = resolve_range(AnalyticsRange.MONTH, today=today)
    assert end == date(2026, 5, 12)
    assert (end - start).days == 29


def test_resolve_range_quarter_ninety_days():
    today = date(2026, 5, 13)
    start, end = resolve_range(AnalyticsRange.QUARTER, today=today)
    assert (end - start).days == 89


def test_resolve_range_year_365_days():
    today = date(2026, 5, 13)
    start, end = resolve_range(AnalyticsRange.YEAR, today=today)
    assert (end - start).days == 364


def test_resolve_range_excludes_today():
    """Today's rollup row hasn't been computed yet — never include it."""
    today = date(2026, 5, 13)
    for r in AnalyticsRange:
        _, end = resolve_range(r, today=today)
        assert end < today
