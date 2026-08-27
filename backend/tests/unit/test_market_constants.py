"""Unit tests for market module constants and pure helper functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.market.constants import (
    BUY_EXPIRY_MINUTES,
    KEYWORD_CONFIDENCE,
    SEED_ALIASES,
    SEED_PRODUCTS,
    SELL_EXPIRY_HOURS,
    AliasSource,
    MarketSide,
    MessageStatus,
    ResolverKind,
    ReviewStatus,
)
from app.modules.market.service import _classify_side, _compute_expiry, _normalize_text

# ----------------------------------------------------------------- constants


@pytest.mark.parametrize(
    "enum_cls,expected_count",
    [
        (MarketSide, 4),
        (MessageStatus, 3),
        (ReviewStatus, 5),
        (ResolverKind, 2),
        (AliasSource, 3),
    ],
)
def test_enum_has_expected_values(enum_cls, expected_count):
    assert len(list(enum_cls)) == expected_count


def test_review_status_values():
    assert ReviewStatus.AUTO.value == "AUTO"
    assert ReviewStatus.PENDING.value == "PENDING"
    assert ReviewStatus.REVIEWED.value == "REVIEWED"
    assert ReviewStatus.DISMISSED.value == "DISMISSED"
    assert ReviewStatus.UNREVIEWED_EXPIRED.value == "UNREVIEWED_EXPIRED"


def test_side_has_mixed():
    assert MarketSide.MIXED.value == "MIXED"


def test_alias_source_has_human():
    assert AliasSource.HUMAN.value == "human"


def test_seed_products_has_apple_and_samsung():
    brands = {p["brand"] for p in SEED_PRODUCTS}
    assert "Apple" in brands
    assert "Samsung" in brands


def test_seed_aliases_reference_known_products():
    canonical_names = {p["canonical_name"] for p in SEED_PRODUCTS}
    for a in SEED_ALIASES:
        assert a["canonical_name"] in canonical_names


def test_keyword_confidence_is_high():
    assert KEYWORD_CONFIDENCE > 0.9


# ----------------------------------------------------------------- normalization


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  iPhone  16  PRO MAX ", "iphone 16 pro max"),
        ("WTS SAMSUNG S25\nULTRA", "wts samsung s25 ultra"),
        ("\tLOOKING FOR\tIPHONE\t", "looking for iphone"),
        ("already clean", "already clean"),
        ("", ""),
    ],
)
def test_normalize_text(raw, expected):
    assert _normalize_text(raw) == expected


# ----------------------------------------------------------------- side classification


@pytest.mark.parametrize(
    "text,expected_side",
    [
        ("wtb iphone 16 pro max 256gb", MarketSide.BUY.value),
        ("want to buy samsung s25", MarketSide.BUY.value),
        ("looking for z flip 6 sealed", MarketSide.BUY.value),
        ("need galaxy s24 ultra", MarketSide.BUY.value),
        ("iso iphone 16 pm", MarketSide.BUY.value),
        ("anyone selling a 16 pro max?", MarketSide.BUY.value),
        ("anyone have a fold 6?", MarketSide.BUY.value),
        ("anyone got s25u available?", MarketSide.BUY.value),
        ("wts iphone 16 pro max 256gb", MarketSide.SELL.value),
        ("want to sell samsung s25", MarketSide.SELL.value),
        ("for sale z flip 6 brand new sealed", MarketSide.SELL.value),
        ("selling my iphone 15 pro", MarketSide.SELL.value),
        ("brandnew s25 ultra in stock", MarketSide.SELL.value),
        ("mint condition 16pm available now", MarketSide.SELL.value),
        ("interested dm me best price", MarketSide.SELL.value),
        ("s25 ultra unopened box sealed", MarketSide.SELL.value),
        ("hello how are you", MarketSide.UNKNOWN.value),
        ("random chatter no signals", MarketSide.UNKNOWN.value),
    ],
)
def test_classify_side(text, expected_side):
    normalized = _normalize_text(text)
    assert _classify_side(normalized) == expected_side


def test_classify_side_buy_wins_over_sell_when_both_patterns():
    """Buy patterns are checked first, so a message with both buy and sell signals classifies as BUY."""
    text = "wtb iphone but also selling samsung"
    assert _classify_side(text) == MarketSide.BUY.value


# ----------------------------------------------------------------- expiry


def test_compute_expiry_buy():
    now = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)
    expiry = _compute_expiry(MarketSide.BUY.value, now)
    assert expiry == now + timedelta(minutes=BUY_EXPIRY_MINUTES)


def test_compute_expiry_sell():
    now = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)
    expiry = _compute_expiry(MarketSide.SELL.value, now)
    assert expiry == now + timedelta(hours=SELL_EXPIRY_HOURS)


def test_compute_expiry_unknown_defaults_to_sell_ttl():
    now = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)
    expiry = _compute_expiry(MarketSide.UNKNOWN.value, now)
    assert expiry == now + timedelta(hours=SELL_EXPIRY_HOURS)
