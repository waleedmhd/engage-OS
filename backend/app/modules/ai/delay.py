"""Realistic delay engine (DSD §4.4).

Pure functions — RNG injectable for deterministic tests.
"""

from __future__ import annotations

import random

from app.modules.messaging.constants import (
    DELAY_LONG_RANGE,
    DELAY_MEDIUM_RANGE,
    DELAY_SHORT_RANGE,
    DELAY_VARIANCE,
)


def _band(words: int) -> tuple[int, int]:
    if words <= 15:
        return DELAY_SHORT_RANGE
    if words <= 60:
        return DELAY_MEDIUM_RANGE
    return DELAY_LONG_RANGE


def compute_delay(reply: str, *, rng: random.Random | None = None) -> int:
    """Return a delay in seconds for the given reply text per DSD §4.4."""
    r = rng or random
    words = len([w for w in reply.split() if w])
    if words == 0:
        return 1
    lo, hi = _band(words)
    base = r.uniform(lo, hi)
    variance = r.uniform(-DELAY_VARIANCE, DELAY_VARIANCE)
    return max(1, int(base * (1 + variance)))
