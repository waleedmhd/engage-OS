"""Unit tests for analytics Celery tasks.

The tasks delegate to ``aggregator.upsert_*`` helpers; we mock those plus
the sync session factory to verify the task scaffolding (target_date
defaulting, backfill iteration, telemetry shape) without a database.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

# Register models before the task module imports them (matches the
# pattern in test_assignment_sweep.py).
from app.db import import_all_models

import_all_models()

from app.modules.analytics import tasks as analytics_tasks  # noqa: E402


@contextmanager
def _session_cm(session):
    yield session


def _patch_factory(monkeypatch, session):
    monkeypatch.setattr(
        analytics_tasks,
        "sync_session_factory",
        lambda: _session_cm(session),
    )


def test_aggregate_daily_defaults_to_yesterday(monkeypatch):
    session = MagicMock()
    _patch_factory(monkeypatch, session)

    calls: list[date] = []
    monkeypatch.setattr(
        analytics_tasks,
        "upsert_global_daily",
        lambda s, d: calls.append(d),
    )
    monkeypatch.setattr(
        analytics_tasks, "upsert_campaign_daily", lambda s, d: 3
    )

    result = analytics_tasks.aggregate_daily_metrics_task.run()
    expected = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    assert result["target_date"] == expected
    assert result["campaigns"] == 3
    assert calls == [date.fromisoformat(expected)]
    session.commit.assert_called_once()


def test_aggregate_daily_honors_explicit_date(monkeypatch):
    session = MagicMock()
    _patch_factory(monkeypatch, session)

    global_calls: list[date] = []
    campaign_calls: list[date] = []
    monkeypatch.setattr(
        analytics_tasks,
        "upsert_global_daily",
        lambda s, d: global_calls.append(d),
    )
    monkeypatch.setattr(
        analytics_tasks,
        "upsert_campaign_daily",
        lambda s, d: (campaign_calls.append(d), 0)[1],
    )

    result = analytics_tasks.aggregate_daily_metrics_task.run(
        target_date_iso="2026-05-01"
    )
    assert result["target_date"] == "2026-05-01"
    assert global_calls == [date(2026, 5, 1)]
    assert campaign_calls == [date(2026, 5, 1)]


def test_backfill_iterates_each_day(monkeypatch):
    sessions: list[MagicMock] = []

    @contextmanager
    def factory():
        s = MagicMock()
        sessions.append(s)
        yield s

    monkeypatch.setattr(analytics_tasks, "sync_session_factory", factory)

    days: list[date] = []
    monkeypatch.setattr(
        analytics_tasks,
        "upsert_global_daily",
        lambda s, d: days.append(d),
    )
    monkeypatch.setattr(
        analytics_tasks, "upsert_campaign_daily", lambda s, d: 1
    )

    result = analytics_tasks.backfill_daily_metrics_task.run(
        "2026-05-10", "2026-05-12"
    )
    assert result["days"] == 3
    assert result["campaigns"] == 3
    assert days == [date(2026, 5, 10), date(2026, 5, 11), date(2026, 5, 12)]
    assert len(sessions) == 3
    for s in sessions:
        s.commit.assert_called_once()


def test_backfill_rejects_inverted_range(monkeypatch):
    monkeypatch.setattr(
        analytics_tasks,
        "sync_session_factory",
        lambda: _session_cm(MagicMock()),
    )

    import pytest

    with pytest.raises(ValueError):
        analytics_tasks.backfill_daily_metrics_task.run(
            "2026-05-12", "2026-05-10"
        )
