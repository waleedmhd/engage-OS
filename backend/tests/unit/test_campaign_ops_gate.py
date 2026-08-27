"""Campaign operational gate: business-hours + daily-cap deferral."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest
from celery.exceptions import Retry

from app.modules.campaigns import tasks as ct
from app.modules.settings.operational import (
    BusinessHours,
    DailyCap,
    OperationalConfig,
)

DUBAI = ZoneInfo("Asia/Dubai")

_DEFER_EXC = (Retry, RuntimeError)


def _cfg(*, bh=False, start="09:00", end="18:00", cap=False, limit=800):
    return OperationalConfig(
        tz=DUBAI,
        business_hours=BusinessHours(
            enabled=bh,
            start=time(int(start[:2]), int(start[3:])),
            end=time(int(end[:2]), int(end[3:])),
        ),
        cap=DailyCap(enabled=cap, limit=limit),
    )


class _FakeRedis:
    def __init__(self, count=0):
        self._count = count

    def get(self, key):
        return str(self._count).encode() if self._count else None


def test_gate_allows_when_all_disabled(monkeypatch):
    monkeypatch.setattr(ct, "read_operational_config_sync", lambda _s: _cfg())
    allowed, countdown, reason = ct._campaign_ops_gate(
        session=object(), redis=_FakeRedis(),
        now_utc=datetime(2026, 5, 20, 2, 0, tzinfo=UTC),
    )
    assert allowed is True
    assert reason is None
    assert countdown is None


def test_gate_defers_outside_business_hours(monkeypatch):
    monkeypatch.setattr(
        ct, "read_operational_config_sync", lambda _s: _cfg(bh=True)
    )
    # 02:00 UTC == 06:00 Dubai, window opens 09:00 Dubai -> 3h
    allowed, countdown, reason = ct._campaign_ops_gate(
        session=object(), redis=_FakeRedis(),
        now_utc=datetime(2026, 5, 20, 2, 0, tzinfo=UTC),
    )
    assert allowed is False
    assert countdown == 3 * 3600
    assert reason == "outside_business_hours"


def test_gate_defers_when_cap_reached(monkeypatch):
    monkeypatch.setattr(
        ct, "read_operational_config_sync",
        lambda _s: _cfg(cap=True, limit=5),
    )
    # 18:00 UTC == 22:00 Dubai -> 2h to local midnight
    allowed, countdown, reason = ct._campaign_ops_gate(
        session=object(), redis=_FakeRedis(count=5),
        now_utc=datetime(2026, 5, 20, 18, 0, tzinfo=UTC),
    )
    assert allowed is False
    assert countdown == 2 * 3600
    assert reason == "daily_cap_reached"


def test_gate_allows_when_cap_not_reached(monkeypatch):
    monkeypatch.setattr(
        ct, "read_operational_config_sync",
        lambda _s: _cfg(cap=True, limit=5),
    )
    allowed, countdown, reason = ct._campaign_ops_gate(
        session=object(), redis=_FakeRedis(count=4),
        now_utc=datetime(2026, 5, 20, 18, 0, tzinfo=UTC),
    )
    assert allowed is True
    assert reason is None
    assert countdown is None


class _FakeRedisPipeline:
    def __init__(self, log):
        self._log = log

    def incr(self, key):
        self._log.append(("incr", key))
        return self

    def expire(self, key, ttl):
        self._log.append(("expire", key, ttl))
        return self

    def execute(self):
        self._log.append(("execute",))
        return [1, True]


class _PipelineRedis:
    def __init__(self):
        self.log: list = []

    def pipeline(self):
        return _FakeRedisPipeline(self.log)


def test_increment_daily_cap_noops_when_disabled(monkeypatch):
    monkeypatch.setattr(
        ct, "read_operational_config_sync", lambda _s: _cfg(cap=False)
    )
    redis = _PipelineRedis()
    ct._increment_daily_cap(session=object(), redis=redis)
    assert redis.log == []


def test_increment_daily_cap_pipelines_incr_and_expire(monkeypatch):
    monkeypatch.setattr(
        ct, "read_operational_config_sync", lambda _s: _cfg(cap=True, limit=10)
    )
    redis = _PipelineRedis()
    ct._increment_daily_cap(session=object(), redis=redis)
    ops = [entry[0] for entry in redis.log]
    assert ops == ["incr", "expire", "execute"]
    # expire TTL is the module constant (48h).
    assert redis.log[1][2] == ct._DAILY_CAP_KEY_TTL_SECONDS
    # The incr key is the daily counter for today's local date.
    assert redis.log[0][1].startswith("campaign:daily_sent:")


def test_dispatch_defers_when_gated(monkeypatch):
    monkeypatch.setattr(ct, "redis_healthy", lambda: True)

    class _R:
        def set(self, *a, **k):
            return True

        def delete(self, *a, **k):
            return None

    monkeypatch.setattr(ct, "get_sync_redis", lambda: _R())
    monkeypatch.setattr(
        ct, "_campaign_ops_gate",
        lambda *a, **k: (False, 3600, "outside_business_hours"),
    )
    # Must defer BEFORE touching the DB/session.
    monkeypatch.setattr(
        ct, "sync_session_factory",
        lambda: (_ for _ in ()).throw(
            AssertionError("session opened despite gated dispatch")
        ),
    )
    with pytest.raises(_DEFER_EXC):
        ct.dispatch_campaign_task.run(str(uuid.uuid4()))


def test_batch_defers_when_gated(monkeypatch):
    monkeypatch.setattr(ct, "redis_healthy", lambda: True)
    monkeypatch.setattr(ct, "get_sync_redis", lambda: object())
    monkeypatch.setattr(
        ct, "_campaign_ops_gate",
        lambda *a, **k: (False, 3600, "daily_cap_reached"),
    )
    monkeypatch.setattr(
        ct, "sync_session_factory",
        lambda: (_ for _ in ()).throw(
            AssertionError("session opened despite gated batch")
        ),
    )
    with pytest.raises(_DEFER_EXC):
        ct.process_campaign_batch_task.run(
            str(uuid.uuid4()), [str(uuid.uuid4())]
        )
