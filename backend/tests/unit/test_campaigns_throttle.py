"""Throttle-bucket logic for campaign batch dispatch.

The bucket is a per-second sliding window in Redis. We use a fake Redis-like
client to verify the algorithm without needing a real Redis.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Any

import pytest

from app.modules.campaigns.tasks import _claim_throttle_slot


class FakeRedis:
    """Minimal Redis surface used by _claim_throttle_slot.

    Only the pipeline.incr/expire flow is required.
    """

    def __init__(self) -> None:
        self.values: dict[str, int] = defaultdict(int)
        self.expirations: dict[str, int] = {}

    def pipeline(self) -> FakeRedisPipeline:
        return FakeRedisPipeline(self)


class FakeRedisPipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self._ops: list[tuple[str, Any, ...]] = []

    def incr(self, key: str) -> FakeRedisPipeline:
        self._ops.append(("incr", key))
        return self

    def expire(self, key: str, ttl: int) -> FakeRedisPipeline:
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self) -> list[Any]:
        results: list[Any] = []
        for op in self._ops:
            if op[0] == "incr":
                self.redis.values[op[1]] += 1
                results.append(self.redis.values[op[1]])
            elif op[0] == "expire":
                self.redis.expirations[op[1]] = op[2]
                results.append(True)
        return results


def test_throttle_admits_up_to_rate() -> None:
    redis = FakeRedis()
    cid = uuid.uuid4()
    rate = 5
    granted = sum(_claim_throttle_slot(redis, cid, rate) for _ in range(5))
    assert granted == 5


def test_throttle_rejects_over_rate() -> None:
    redis = FakeRedis()
    cid = uuid.uuid4()
    rate = 5
    for _ in range(rate):
        assert _claim_throttle_slot(redis, cid, rate) is True
    # 6th call in the same second is denied.
    assert _claim_throttle_slot(redis, cid, rate) is False
    assert _claim_throttle_slot(redis, cid, rate) is False


def test_throttle_buckets_separate_per_campaign() -> None:
    redis = FakeRedis()
    a, b = uuid.uuid4(), uuid.uuid4()
    rate = 2
    assert _claim_throttle_slot(redis, a, rate)
    assert _claim_throttle_slot(redis, a, rate)
    # Campaign A is exhausted, but Campaign B has its own bucket.
    assert _claim_throttle_slot(redis, a, rate) is False
    assert _claim_throttle_slot(redis, b, rate) is True
    assert _claim_throttle_slot(redis, b, rate) is True


def test_throttle_resets_in_next_epoch_second(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    cid = uuid.uuid4()
    rate = 1

    fake_time = [1_700_000_000]
    monkeypatch.setattr(time, "time", lambda: fake_time[0])

    assert _claim_throttle_slot(redis, cid, rate) is True
    assert _claim_throttle_slot(redis, cid, rate) is False
    fake_time[0] += 1
    # New epoch second → fresh bucket key → admits 1 again.
    assert _claim_throttle_slot(redis, cid, rate) is True
