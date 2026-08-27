"""DSD §4.4 — realistic delay engine."""

import random

import pytest

from app.modules.ai.delay import compute_delay
from app.modules.messaging.constants import (
    DELAY_LONG_RANGE,
    DELAY_MEDIUM_RANGE,
    DELAY_SHORT_RANGE,
    DELAY_VARIANCE,
)


def _bounds(lo: int, hi: int) -> tuple[float, float]:
    return lo * (1 - DELAY_VARIANCE), hi * (1 + DELAY_VARIANCE)


@pytest.mark.parametrize(
    "reply,band",
    [
        ("one", DELAY_SHORT_RANGE),
        (" ".join(["w"] * 15), DELAY_SHORT_RANGE),
        (" ".join(["w"] * 16), DELAY_MEDIUM_RANGE),
        (" ".join(["w"] * 60), DELAY_MEDIUM_RANGE),
        (" ".join(["w"] * 61), DELAY_LONG_RANGE),
        (" ".join(["w"] * 200), DELAY_LONG_RANGE),
    ],
)
def test_delay_band_boundaries(reply: str, band: tuple[int, int]) -> None:
    rng = random.Random(42)
    lo_with_var, hi_with_var = _bounds(*band)
    for _ in range(50):
        d = compute_delay(reply, rng=rng)
        assert d >= 1
        assert lo_with_var - 1 <= d <= hi_with_var + 1


def test_delay_empty_reply_returns_min() -> None:
    assert compute_delay("") == 1
    assert compute_delay("   ") == 1


def test_delay_deterministic_with_seeded_rng() -> None:
    rng_a = random.Random(7)
    rng_b = random.Random(7)
    reply = "hello there friend"
    assert compute_delay(reply, rng=rng_a) == compute_delay(reply, rng=rng_b)
