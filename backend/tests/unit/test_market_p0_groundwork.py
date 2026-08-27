"""Unit tests for P0 groundwork — new enum values, config, settings seeds."""

from __future__ import annotations

from app.core.config import Settings
from app.modules.market.constants import (
    AliasSource,
    MarketSide,
    ReviewStatus,
)
from app.modules.settings.constants import (
    MARKET_CONFIDENCE_DEFAULTS,
    SETTING_MARKET_CONFIDENCE_AUTO_MIN,
    SETTING_MARKET_CONFIDENCE_REVIEW_MIN,
)


def test_config_market_trust_listener_default():
    s = Settings()
    assert s.MARKET_TRUST_LISTENER is True


def test_config_fingerprint_window_default():
    s = Settings()
    assert s.MARKET_FINGERPRINT_WINDOW_HOURS == 3


def test_market_side_has_mixed():
    assert MarketSide("MIXED") is MarketSide.MIXED


def test_alias_source_has_human():
    assert AliasSource("human") is AliasSource.HUMAN


class TestReviewStatus:
    @staticmethod
    def test_all_values_roundtrip():
        for v in ("AUTO", "PENDING", "REVIEWED", "DISMISSED", "UNREVIEWED_EXPIRED"):
            assert ReviewStatus(v).value == v

    @staticmethod
    def test_has_five_members():
        assert len(list(ReviewStatus)) == 5


class TestMarketConfidenceSettings:
    def test_auto_min_key(self):
        assert SETTING_MARKET_CONFIDENCE_AUTO_MIN == "market.confidence.auto_min"

    def test_review_min_key(self):
        assert SETTING_MARKET_CONFIDENCE_REVIEW_MIN == "market.confidence.review_min"

    def test_auto_min_default(self):
        assert MARKET_CONFIDENCE_DEFAULTS[SETTING_MARKET_CONFIDENCE_AUTO_MIN] == {"value": 0.85}

    def test_review_min_default(self):
        assert MARKET_CONFIDENCE_DEFAULTS[SETTING_MARKET_CONFIDENCE_REVIEW_MIN] == {"value": 0.55}
