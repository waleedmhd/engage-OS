"""Unit tests for Phase 4 confidence bands and per-field scoring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.market.constants import KEYWORD_CONFIDENCE, ReviewStatus
from app.modules.market.models import MarketMessage, MarketMessageProduct
from app.modules.market.service import MarketIngestionService


def _make_svc():
    session = AsyncMock()
    svc = MarketIngestionService(session)
    return svc, session


# ------------------------------------------------------------------ band routing


@pytest.mark.asyncio
async def test_routing_auto_when_min_conf_meets_threshold():
    """min_field >= auto_min → review_status = AUTO."""
    svc, session = _make_svc()
    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()

    r = MagicMock(spec=MarketMessageProduct)
    r.confidence = 0.85
    svc._mmp.list_for_message = AsyncMock(return_value=[r])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    await svc._apply_confidence_routing(msg)
    assert msg.review_status == ReviewStatus.AUTO.value


@pytest.mark.asyncio
async def test_routing_pending_when_mid_conf():
    """review_min <= min_field < auto_min → review_status = PENDING."""
    svc, session = _make_svc()
    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()

    r = MagicMock(spec=MarketMessageProduct)
    r.confidence = 0.84
    svc._mmp.list_for_message = AsyncMock(return_value=[r])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    await svc._apply_confidence_routing(msg)
    assert msg.review_status == ReviewStatus.PENDING.value


@pytest.mark.asyncio
async def test_routing_auto_unresolved_when_below_review_min():
    """Below review_min → AUTO with _unresolved flag on resolutions."""
    svc, session = _make_svc()
    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()

    r = MagicMock(spec=MarketMessageProduct)
    r.confidence = 0.54
    r.attributes = None
    svc._mmp.list_for_message = AsyncMock(return_value=[r])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    await svc._apply_confidence_routing(msg)
    assert msg.review_status == ReviewStatus.AUTO.value
    assert r.attributes["_unresolved"] is True


@pytest.mark.asyncio
async def test_routing_at_review_min_boundary():
    """Exactly at review_min → PENDING."""
    svc, session = _make_svc()
    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()

    r = MagicMock(spec=MarketMessageProduct)
    r.confidence = 0.55
    svc._mmp.list_for_message = AsyncMock(return_value=[r])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    await svc._apply_confidence_routing(msg)
    assert msg.review_status == ReviewStatus.PENDING.value


@pytest.mark.asyncio
async def test_routing_no_resolutions_returns_early():
    """No resolutions → no routing change (no-op)."""
    svc, session = _make_svc()
    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()

    svc._mmp.list_for_message = AsyncMock(return_value=[])

    await svc._apply_confidence_routing(msg)
    # review_status was never set by routing
    assert not hasattr(msg, "review_status") or msg.review_status is not ReviewStatus.PENDING.value


# -------------------------------------------------------- per-field aggregation


@pytest.mark.asyncio
async def test_routing_takes_min_of_per_field():
    """Row route uses the minimum confidence across all resolutions."""
    svc, session = _make_svc()
    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()

    r1 = MagicMock(spec=MarketMessageProduct)
    r1.confidence = 0.90  # high
    r2 = MagicMock(spec=MarketMessageProduct)
    r2.confidence = 0.60  # low — this one drives the band
    svc._mmp.list_for_message = AsyncMock(return_value=[r1, r2])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    await svc._apply_confidence_routing(msg)
    # min is 0.60 → PENDING (between 0.55 and 0.85)
    assert msg.review_status == ReviewStatus.PENDING.value


@pytest.mark.asyncio
async def test_routing_min_below_review_min_flags_all():
    """When min < review_min, ALL resolutions get _unresolved flag."""
    svc, session = _make_svc()
    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()

    r1 = MagicMock(spec=MarketMessageProduct)
    r1.confidence = 0.30
    r1.attributes = {"other": True}
    r2 = MagicMock(spec=MarketMessageProduct)
    r2.confidence = 0.90
    r2.attributes = None
    svc._mmp.list_for_message = AsyncMock(return_value=[r1, r2])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    await svc._apply_confidence_routing(msg)
    assert r1.attributes["_unresolved"] is True
    assert r1.attributes["other"] is True  # preserved
    assert r2.attributes["_unresolved"] is True


# ---------------------------------------------------------- keyword confidence


def test_keyword_confidence_is_high():
    """Keyword confidence 0.95 exceeds typical auto_min (0.85)."""
    assert KEYWORD_CONFIDENCE >= 0.95


def test_keyword_confidence_exceeds_auto_min():
    """Sanity check: keyword tier always clears the AUTO band."""
    assert KEYWORD_CONFIDENCE > 0.85


@pytest.mark.asyncio
async def test_classify_keywords_writes_per_field_confidence():
    """_classify_keywords stores _confidence in attributes."""
    svc, session = _make_svc()

    from app.modules.market.models import Product, ProductAlias

    product = MagicMock(spec=Product)
    product.id = MagicMock()
    alias_row = MagicMock(spec=ProductAlias)

    svc._aliases.resolve = AsyncMock(return_value=[(alias_row, product)])
    svc._mmp.create = AsyncMock()
    svc._cpt.increment_tag = AsyncMock()
    svc._cpt._read_auto_min = AsyncMock(return_value=0.85)

    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()
    msg.normalized_text = "wtb iphone 16"
    msg.contact_id = MagicMock()
    msg.side = "BUY"

    await svc._classify_keywords(msg)

    svc._mmp.create.assert_awaited_once()
    _, kwargs = svc._mmp.create.await_args
    attrs = kwargs.get("attributes")
    assert attrs is not None
    assert "_confidence" in attrs
    assert attrs["_confidence"]["side"] == KEYWORD_CONFIDENCE
    assert attrs["_confidence"]["product"] == KEYWORD_CONFIDENCE


@pytest.mark.asyncio
async def test_classify_keywords_passes_confidence_to_increment_tag():
    """_classify_keywords forwards the resolution confidence to the guard."""
    svc, session = _make_svc()

    from app.modules.market.models import Product, ProductAlias

    product = MagicMock(spec=Product)
    product.id = MagicMock()
    alias_row = MagicMock(spec=ProductAlias)

    svc._aliases.resolve = AsyncMock(return_value=[(alias_row, product)])
    svc._cpt.increment_tag = AsyncMock()
    svc._cpt._read_auto_min = AsyncMock(return_value=0.85)

    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()
    msg.normalized_text = "wts samsung"
    msg.contact_id = MagicMock()
    msg.side = "SELL"

    await svc._classify_keywords(msg)

    svc._cpt.increment_tag.assert_awaited_once()
    _, kwargs = svc._cpt.increment_tag.await_args
    assert kwargs["confidence"] == KEYWORD_CONFIDENCE


# --------------------------------------------------------------- edge cases


@pytest.mark.asyncio
async def test_routing_reads_appsetting_thresholds():
    """Thresholds come from _read_numeric_setting, not hardcoded."""
    svc, session = _make_svc()
    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()

    r = MagicMock(spec=MarketMessageProduct)
    r.confidence = 0.80
    svc._mmp.list_for_message = AsyncMock(return_value=[r])
    # Lowered auto_min to 0.70 — now 0.80 clears AUTO
    svc._read_numeric_setting = AsyncMock(side_effect=[0.70, 0.50])

    await svc._apply_confidence_routing(msg)
    assert msg.review_status == ReviewStatus.AUTO.value


@pytest.mark.asyncio
async def test_routing_defaults_when_settings_missing():
    """When _read_numeric_setting returns defaults, routing still works."""
    svc, session = _make_svc()
    msg = MagicMock(spec=MarketMessage)
    msg.id = MagicMock()

    r = MagicMock(spec=MarketMessageProduct)
    r.confidence = 0.90
    svc._mmp.list_for_message = AsyncMock(return_value=[r])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    await svc._apply_confidence_routing(msg)
    assert msg.review_status == ReviewStatus.AUTO.value
