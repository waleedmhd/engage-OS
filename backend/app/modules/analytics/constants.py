"""Analytics enums + helpers (DSD §4.9)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

# Last-touch revenue attribution window: a contact's revenue counts for the
# campaign whose most recent responded message landed within this many days
# of the metric date.
ATTRIBUTION_WINDOW_DAYS = 30


class AnalyticsRange(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


_RANGE_DAYS: dict[AnalyticsRange, int] = {
    AnalyticsRange.DAY: 1,
    AnalyticsRange.WEEK: 7,
    AnalyticsRange.MONTH: 30,
    AnalyticsRange.QUARTER: 90,
    AnalyticsRange.YEAR: 365,
}


def resolve_range(
    range_: AnalyticsRange, *, today: date | None = None
) -> tuple[date, date]:
    """Return ``(start_date, end_date)`` inclusive for the given range.

    The window always ends at yesterday (UTC) because today's rollup row
    has not been computed yet — the aggregation job runs at 00:15 UTC for
    the previous day.

    ``DAY`` collapses to a single date (start == end == yesterday).
    """
    if today is None:
        today = datetime.now(UTC).date()
    end = today - timedelta(days=1)
    span = _RANGE_DAYS[range_]
    start = end - timedelta(days=span - 1)
    return start, end
