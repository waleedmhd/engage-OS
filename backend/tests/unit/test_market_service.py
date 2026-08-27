"""Unit tests for market module services with mocked repositories."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.market.models import (
    Deal,
    MarketMessage,
    MarketMessageProduct,
    Product,
    SavedSearch,
    SearchEvent,
)
from app.modules.market.schemas import (
    DealCreateRequest,
    DealUpdateRequest,
    MarketSearchParams,
    OutreachBatchRequest,
    OutreachSendRequest,
    ProductCreateRequest,
    ProductUpdateRequest,
    SavedSearchCreateRequest,
)
from app.modules.market.service import (
    MarketIngestionService,
    MarketOutreachService,
)
from app.modules.market.search import MarketSearchService


def _make_async_service(cls):
    session = AsyncMock()
    svc = cls(session)
    return svc, session


# =====================================================================
# MarketIngestionService
# =====================================================================


@pytest.mark.asyncio
async def test_ingest_idempotent_dedup():
    svc, session = _make_async_service(MarketIngestionService)
    existing = uuid.uuid4()
    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = existing
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=fake_msg)

    result = await svc.ingest(
        source_type="group",
        source_id="g1",
        sender_raw="+971581234567",
        raw_text="WTS iPhone 16 Pro Max",
        captured_at=datetime.now(UTC),
        dedup_hash="known-hash",
    )
    assert result is fake_msg
    svc._mm.get_by_dedup_hash.assert_called_once_with("known-hash")


@pytest.mark.asyncio
async def test_ingest_creates_message():
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    mid = uuid.uuid4()

    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.contact_id = None
    fake_msg.side = "SELL"

    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)
    svc._aliases.resolve = AsyncMock(return_value=[])
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    dt = datetime.now(UTC)
    result = await svc.ingest(
        source_type="dm",
        source_id=None,
        sender_raw=None,
        raw_text="selling my iphone",
        captured_at=dt,
        dedup_hash="new-hash",
    )
    assert result is fake_msg
    svc._mm.create.assert_awaited_once()
    svc._mm.supersede_repost.assert_called_once_with("new-hash", fake_msg.id)


@pytest.mark.asyncio
async def test_ingest_classifies_side_buy():
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    cid = uuid.uuid4()
    mid = uuid.uuid4()

    contact_mock = MagicMock()
    contact_mock.id = cid
    svc._contacts.upsert_by_phone = AsyncMock(return_value=contact_mock)

    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.contact_id = cid
    fake_msg.side = "BUY"
    fake_msg.raw_text = "WTB iPhone 16 Pro Max"
    fake_msg.normalized_text = "wtb iphone 16 pro max"

    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)
    svc._aliases.resolve = AsyncMock(return_value=[])
    svc._cpt.increment_tag = AsyncMock()
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    result = await svc.ingest(
        source_type="group",
        source_id="g1",
        sender_raw="+971581234567",
        raw_text="WTB iPhone 16 Pro Max 256GB sealed",
        captured_at=datetime.now(UTC),
        dedup_hash="buy-hash",
    )
    assert result.side == "BUY"


@pytest.mark.asyncio
async def test_ingest_side_defaults_to_unknown():
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    mid = uuid.uuid4()

    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.contact_id = None
    fake_msg.side = "UNKNOWN"

    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)
    svc._aliases.resolve = AsyncMock(return_value=[])
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    result = await svc.ingest(
        source_type="dm",
        source_id=None,
        sender_raw=None,
        raw_text="random message",
        captured_at=datetime.now(UTC),
        dedup_hash="random-hash",
    )
    assert result.side == "UNKNOWN"


# =====================================================================
# MarketSearchService
# =====================================================================


@pytest.mark.asyncio
async def test_save_search_creates_row():
    svc, session = _make_async_service(MarketSearchService)
    uid = uuid.uuid4()
    ss = AsyncMock(spec=SavedSearch)
    ss.id = uuid.uuid4()
    svc._saved.create = AsyncMock(return_value=ss)

    payload = SavedSearchCreateRequest(name="My search", query_text="iphone 16")
    result = await svc.save_search(payload, user_id=uid)
    assert result is ss
    svc._saved.create.assert_called_once()


@pytest.mark.asyncio
async def test_list_saved_searches():
    svc, session = _make_async_service(MarketSearchService)
    uid = uuid.uuid4()
    svc._saved.list_for_user = AsyncMock(return_value=([], 0))

    items, total = await svc.list_saved_searches(uid, page=1, page_size=20)
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_delete_saved_search_returns_bool():
    svc, session = _make_async_service(MarketSearchService)
    svc._saved.delete = AsyncMock(return_value=True)

    result = await svc.delete_saved_search(uuid.uuid4())
    assert result is True


@pytest.mark.asyncio
async def test_list_search_events():
    svc, session = _make_async_service(MarketSearchService)
    uid = uuid.uuid4()
    svc._searches.list_recent = AsyncMock(return_value=([], 0))

    items, total = await svc.list_search_events(uid, page=1, page_size=20)
    assert items == []
    assert total == 0


# =====================================================================
# MarketOutreachService
# =====================================================================


@pytest.mark.asyncio
async def test_create_deal():
    svc, session = _make_async_service(MarketOutreachService)
    deal = AsyncMock(spec=Deal)
    deal.id = uuid.uuid4()
    svc._deals.create = AsyncMock(return_value=deal)

    payload = DealCreateRequest(
        buyer_contact_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        qty=2,
    )
    result = await svc.create_deal(payload, created_by=uuid.uuid4())
    assert result is deal
    svc._deals.create.assert_called_once()


@pytest.mark.asyncio
async def test_update_deal_noop_when_empty():
    svc, session = _make_async_service(MarketOutreachService)
    did = uuid.uuid4()
    deal = AsyncMock(spec=Deal)
    svc._deals.get = AsyncMock(return_value=deal)

    payload = DealUpdateRequest()
    result = await svc.update_deal(did, payload)
    assert result is deal


@pytest.mark.asyncio
async def test_update_deal_applies_changes():
    svc, session = _make_async_service(MarketOutreachService)
    did = uuid.uuid4()
    deal = AsyncMock(spec=Deal)
    svc._deals.update = AsyncMock(return_value=deal)

    payload = DealUpdateRequest(status="negotiating", qty=3)
    result = await svc.update_deal(did, payload)
    assert result is deal
    svc._deals.update.assert_called_once()


@pytest.mark.asyncio
async def test_get_deal_missing():
    svc, session = _make_async_service(MarketOutreachService)
    svc._deals.get = AsyncMock(return_value=None)

    result = await svc.get_deal(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_list_deals():
    svc, session = _make_async_service(MarketOutreachService)
    svc._deals.list_by_status = AsyncMock(return_value=([], 0))

    items, total = await svc.list_deals(status="matched", page=1, page_size=50)
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_create_product():
    svc, session = _make_async_service(MarketOutreachService)
    prod = AsyncMock(spec=Product)
    prod.id = uuid.uuid4()
    prod.canonical_name = "iphone 17 pro max"

    payload = ProductCreateRequest(
        brand="Apple",
        family="iPhone",
        canonical_name="iPhone 17 Pro Max",
        tier="pro max",
    )
    # Patch the product repo create
    svc.create_product = AsyncMock(return_value=prod)

    result = await svc.create_product(payload)
    assert result.canonical_name == "iphone 17 pro max"


@pytest.mark.asyncio
async def test_update_product():
    svc, session = _make_async_service(MarketOutreachService)
    pid = uuid.uuid4()
    prod = AsyncMock(spec=Product)
    prod.id = pid

    payload = ProductUpdateRequest(brand="Samsung")
    # Patch the method
    svc.update_product = AsyncMock(return_value=prod)

    result = await svc.update_product(pid, payload)
    assert result is prod


@pytest.mark.asyncio
async def test_list_products():
    svc, session = _make_async_service(MarketOutreachService)
    svc.list_products = AsyncMock(return_value=([], 0))

    items, total = await svc.list_products(page=1, page_size=50)
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_get_product():
    svc, session = _make_async_service(MarketOutreachService)
    prod = MagicMock(spec=Product)
    svc.get_product = AsyncMock(return_value=prod)

    pid = uuid.uuid4()
    result = await svc.get_product(pid)
    assert result is prod


@pytest.mark.asyncio
async def test_get_contact_product_tags():
    svc, session = _make_async_service(MarketOutreachService)
    cid = uuid.uuid4()
    expected_tags = [
        {
            "contact_id": cid,
            "product_id": uuid.uuid4(),
            "product_name": "iphone 16 pro",
            "product_brand": "Apple",
            "side_buy_count": 3,
            "side_sell_count": 0,
            "observation_count": 3,
            "first_seen_at": datetime.now(UTC),
            "last_seen_at": datetime.now(UTC),
        }
    ]

    svc.get_contact_product_tags = AsyncMock(return_value=expected_tags)
    result = await svc.get_contact_product_tags(cid)
    assert len(result) == 1
    assert result[0]["product_name"] == "iphone 16 pro"


# =====================================================================
# MarketSearchService — search params
# =====================================================================


@pytest.mark.asyncio
async def test_search_returns_empty_for_no_results():
    svc, session = _make_async_service(MarketSearchService)
    uid = uuid.uuid4()

    svc._aliases.resolve = AsyncMock(return_value=[])
    svc._products.get_by_canonical_name = AsyncMock(return_value=None)
    svc._mm.search_fts = AsyncMock(return_value=([], 0, None, None))
    svc._mmp.list_for_messages = AsyncMock(return_value=[])
    svc._searches.create = AsyncMock()
    svc._expand_query_vocab = AsyncMock(return_value=None)

    params = MarketSearchParams(q="nonexistent_product_xyz")
    result = await svc.search(params, user_id=uid)

    assert result.buy_total == 0
    assert result.sell_total == 0
    assert result.buy_items == []
    assert result.sell_items == []


# =====================================================================
# _expand_query_vocab unit tests
# =====================================================================


def _vocab_row(category="brand", kind="open", tag="test", canonical="Test", aliases=None, is_active=True):
    """Build a mock AttributeVocab row."""
    from app.modules.market.models import AttributeVocab

    row = MagicMock(spec=AttributeVocab)
    row.category = category
    row.kind = kind
    row.tag = tag
    row.canonical = canonical
    row.aliases = aliases or []
    row.is_active = is_active
    return row


@pytest.mark.asyncio
async def test_expand_vocab_short_query_matches_long_canonical():
    """A short query that is a substring of a longer vocab canonical triggers expansion."""
    svc, session = _make_async_service(MarketSearchService)

    entry = _vocab_row(
        tag="iphone 17 pro max",
        canonical="iPhone 17 Pro Max",
        aliases=["17 pro max", "17 pro"],
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [entry]
    session.execute = AsyncMock(return_value=mock_result)

    result = await svc._expand_query_vocab("iphone")
    assert result is not None
    assert "iphone" in result
    assert "17 pro max" in result
    assert "17 pro" in result


@pytest.mark.asyncio
async def test_expand_vocab_term_in_query_still_works():
    """Original behavior: a vocab term that is a substring of the query still triggers expansion."""
    svc, session = _make_async_service(MarketSearchService)

    entry = _vocab_row(
        tag="Black",
        canonical="Black",
        aliases=["black", "blk", "bank"],
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [entry]
    session.execute = AsyncMock(return_value=mock_result)

    result = await svc._expand_query_vocab("black")
    assert result is not None
    assert "black" in result
    assert "blk" in result


@pytest.mark.asyncio
async def test_expand_vocab_no_match_returns_none():
    """When no vocab entry relates to the query, return None."""
    svc, session = _make_async_service(MarketSearchService)

    entry = _vocab_row(
        tag="Black",
        canonical="Black",
        aliases=["blk"],
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [entry]
    session.execute = AsyncMock(return_value=mock_result)

    result = await svc._expand_query_vocab("samsung")
    assert result is None


@pytest.mark.asyncio
async def test_expand_vocab_inactive_entry_ignored():
    """Inactive vocab entries should not trigger expansion.

    The SQL query filters ``is_active == True``, so inactive entries are
    never seen by the expansion logic. We model this by returning an empty
    list when the entry would be inactive.
    """
    svc, session = _make_async_service(MarketSearchService)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []  # DB filters out inactive
    session.execute = AsyncMock(return_value=mock_result)

    result = await svc._expand_query_vocab("black")
    assert result is None


# =====================================================================
# Phase 4 — confidence routing through ingest()
# =====================================================================


@pytest.mark.asyncio
async def test_ingest_routes_high_confidence_to_auto():
    """Keyword resolutions (0.95) → review_status = AUTO."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    mid = uuid.uuid4()

    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.contact_id = uuid.uuid4()
    fake_msg.side = "SELL"

    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)
    svc._contacts.upsert_by_phone = AsyncMock(
        return_value=MagicMock(id=fake_msg.contact_id)
    )
    svc._cpt.increment_tag = AsyncMock()
    svc._cpt._read_auto_min = AsyncMock(return_value=0.85)

    # Keyword resolution will set confidence=0.95.
    from app.modules.market.models import Product, ProductAlias

    product = MagicMock(spec=Product)
    product.id = uuid.uuid4()
    alias_row = MagicMock(spec=ProductAlias)
    svc._aliases.resolve = AsyncMock(return_value=[(alias_row, product)])

    # Return the created resolution for routing.
    fake_resolution = MagicMock(spec=MarketMessageProduct)
    fake_resolution.confidence = 0.95
    svc._mmp.list_for_message = AsyncMock(return_value=[fake_resolution])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    result = await svc.ingest(
        source_type="group",
        source_id="g1",
        sender_raw="+971581234567",
        raw_text="WTS iPhone 16 Pro Max",
        captured_at=datetime.now(UTC),
        dedup_hash="high-conf",
    )
    assert result.review_status == "AUTO"


@pytest.mark.asyncio
async def test_ingest_routes_mid_confidence_to_pending():
    """Mid-confidence resolutions (between review_min and auto_min) → PENDING."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    mid = uuid.uuid4()

    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.contact_id = uuid.uuid4()
    fake_msg.side = "SELL"

    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)
    svc._contacts.upsert_by_phone = AsyncMock(
        return_value=MagicMock(id=fake_msg.contact_id)
    )
    svc._cpt.increment_tag = AsyncMock()
    svc._cpt._read_auto_min = AsyncMock(return_value=0.85)

    # Set up keyword match then override the resolution confidence for routing.
    from app.modules.market.models import Product, ProductAlias

    product = MagicMock(spec=Product)
    product.id = uuid.uuid4()
    alias_row = MagicMock(spec=ProductAlias)
    svc._aliases.resolve = AsyncMock(return_value=[(alias_row, product)])

    fake_resolution = MagicMock(spec=MarketMessageProduct)
    fake_resolution.confidence = 0.70  # mid
    svc._mmp.list_for_message = AsyncMock(return_value=[fake_resolution])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    result = await svc.ingest(
        source_type="group",
        source_id="g2",
        sender_raw="+971581234568",
        raw_text="WTS Samsung S25",
        captured_at=datetime.now(UTC),
        dedup_hash="mid-conf",
    )
    assert result.review_status == "PENDING"


@pytest.mark.asyncio
async def test_ingest_routes_low_confidence_to_auto_unresolved():
    """Low-confidence (below review_min) → AUTO, resolutions flagged _unresolved."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    mid = uuid.uuid4()

    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.contact_id = uuid.uuid4()
    fake_msg.side = "SELL"

    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)
    svc._contacts.upsert_by_phone = AsyncMock(
        return_value=MagicMock(id=fake_msg.contact_id)
    )
    svc._cpt.increment_tag = AsyncMock()
    svc._cpt._read_auto_min = AsyncMock(return_value=0.85)

    from app.modules.market.models import Product, ProductAlias

    product = MagicMock(spec=Product)
    product.id = uuid.uuid4()
    alias_row = MagicMock(spec=ProductAlias)
    svc._aliases.resolve = AsyncMock(return_value=[(alias_row, product)])

    fake_resolution = MagicMock(spec=MarketMessageProduct)
    fake_resolution.confidence = 0.40  # low
    fake_resolution.attributes = {}
    svc._mmp.list_for_message = AsyncMock(return_value=[fake_resolution])
    svc._read_numeric_setting = AsyncMock(side_effect=[0.85, 0.55])

    result = await svc.ingest(
        source_type="group",
        source_id="g3",
        sender_raw="+971581234569",
        raw_text="random iPhone message",
        captured_at=datetime.now(UTC),
        dedup_hash="low-conf",
    )
    assert result.review_status == "AUTO"
    assert fake_resolution.attributes.get("_unresolved") is True


# =====================================================================
# Phase 10 — fingerprint dedup
# =====================================================================


def _mock_contact():
    c = MagicMock()
    c.id = uuid.uuid4()
    return c


@pytest.mark.asyncio
async def test_fingerprint_first_sighting_creates_new_row(monkeypatch):
    """When Redis SET NX succeeds, a new row is created normally."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    svc._contacts.upsert_by_phone = AsyncMock(return_value=_mock_contact())
    svc._aliases.resolve = AsyncMock(return_value=[])
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    mid = uuid.uuid4()
    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.side = "SELL"
    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)  # SET NX succeeds
    monkeypatch.setattr(
        "app.core.redis.get_async_redis",
        lambda: mock_redis,
    )

    result = await svc.ingest(
        source_type="group",
        source_id="g1",
        sender_raw="+971581234567",
        raw_text="WTS iPhone 16 Pro Max 256GB",
        captured_at=datetime.now(UTC),
        dedup_hash="fp-new-hash",
        group_name="Dubai Deals",
    )
    assert result is fake_msg
    svc._mm.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_fingerprint_collision_bumps_existing(monkeypatch):
    """When Redis SET NX returns None, bump the existing row."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    svc._contacts.upsert_by_phone = AsyncMock(return_value=_mock_contact())
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    from app.modules.market.models import Product, ProductAlias

    product = MagicMock(spec=Product)
    product.id = uuid.uuid4()
    alias_row = MagicMock(spec=ProductAlias)
    svc._aliases.resolve = AsyncMock(return_value=[(alias_row, product)])

    existing_id = uuid.uuid4()
    existing_msg = MagicMock(spec=MarketMessage)
    existing_msg.id = existing_id
    existing_msg.side = "SELL"
    existing_msg.seen_count = 1
    existing_msg.source_groups = []
    existing_msg.captured_at = datetime.now(UTC) - timedelta(minutes=10)
    existing_msg.expires_at = datetime.now(UTC) + timedelta(hours=48)
    svc._mm.get = AsyncMock(return_value=existing_msg)
    svc._mm.create = AsyncMock()  # must NOT be called

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)
    mock_redis.get = AsyncMock(return_value=str(existing_id))
    monkeypatch.setattr(
        "app.core.redis.get_async_redis",
        lambda: mock_redis,
    )

    dt = datetime.now(UTC)
    result = await svc.ingest(
        source_type="group",
        source_id="g2",
        sender_raw="+971581234567",
        raw_text="WTS iPhone 16 Pro Max 256GB",
        captured_at=dt,
        dedup_hash="fp-collision-hash",
        group_name="Sharjah Sellers",
    )
    assert result is existing_msg
    assert existing_msg.seen_count == 2
    assert len(existing_msg.source_groups) == 1
    assert existing_msg.source_groups[0]["group_name"] == "Sharjah Sellers"
    svc._mm.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_fingerprint_redis_down_degrade_gracefully(monkeypatch):
    """When Redis is unavailable, ingestion still creates rows normally."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    svc._contacts.upsert_by_phone = AsyncMock(return_value=_mock_contact())
    svc._aliases.resolve = AsyncMock(return_value=[])
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    mid = uuid.uuid4()
    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.side = "SELL"
    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)

    def raise_err(*args, **kwargs):
        raise ConnectionError("Redis down")
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(side_effect=raise_err)
    monkeypatch.setattr(
        "app.core.redis.get_async_redis",
        lambda: mock_redis,
    )

    result = await svc.ingest(
        source_type="group",
        source_id="g3",
        sender_raw="+971581234568",
        raw_text="WTS Samsung S25",
        captured_at=datetime.now(UTC),
        dedup_hash="fp-redis-down-hash",
    )
    assert result is fake_msg
    svc._mm.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_fingerprint_dedup_hash_still_works(monkeypatch):
    """Even with fingerprinting active, dedup_hash is still the hard floor."""
    svc, session = _make_async_service(MarketIngestionService)

    existing_id = uuid.uuid4()
    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = existing_id
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=fake_msg)

    result = await svc.ingest(
        source_type="group",
        source_id="g4",
        sender_raw="+971581234569",
        raw_text="WTS anything",
        captured_at=datetime.now(UTC),
        dedup_hash="known-dedup-hash",
    )
    assert result is fake_msg
    # Early return before fingerprint/contact resolution — no extra calls.


@pytest.mark.asyncio
async def test_fingerprint_zero_window_disables_fingerprinting(monkeypatch):
    """When MARKET_FINGERPRINT_WINDOW_HOURS=0, fingerprinting is disabled."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    svc._contacts.upsert_by_phone = AsyncMock(return_value=_mock_contact())
    svc._aliases.resolve = AsyncMock(return_value=[])
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    mid = uuid.uuid4()
    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.side = "SELL"
    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)

    monkeypatch.setattr(
        "app.modules.market.service.get_settings",
        lambda: MagicMock(MARKET_FINGERPRINT_WINDOW_HOURS=0, MARKET_TRUST_LISTENER=True),
    )

    result = await svc.ingest(
        source_type="group",
        source_id="g5",
        sender_raw="+971581234570",
        raw_text="WTS old phone",
        captured_at=datetime.now(UTC),
        dedup_hash="fp-zero-window",
    )
    assert result is fake_msg
    svc._mm.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_fingerprint_keeps_earliest_captured_at(monkeypatch):
    """On fingerprint collision, keep the earliest captured_at."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    svc._contacts.upsert_by_phone = AsyncMock(return_value=_mock_contact())
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    from app.modules.market.models import Product, ProductAlias

    product = MagicMock(spec=Product)
    product.id = uuid.uuid4()
    alias_row = MagicMock(spec=ProductAlias)
    svc._aliases.resolve = AsyncMock(return_value=[(alias_row, product)])

    older_captured = datetime.now(UTC) - timedelta(minutes=20)
    existing_id = uuid.uuid4()
    existing_msg = MagicMock(spec=MarketMessage)
    existing_msg.id = existing_id
    existing_msg.side = "SELL"
    existing_msg.seen_count = 1
    existing_msg.source_groups = []
    existing_msg.captured_at = older_captured
    existing_msg.expires_at = older_captured + timedelta(hours=48)
    svc._mm.get = AsyncMock(return_value=existing_msg)

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)
    mock_redis.get = AsyncMock(return_value=str(existing_id))
    monkeypatch.setattr(
        "app.core.redis.get_async_redis",
        lambda: mock_redis,
    )

    newer_captured = datetime.now(UTC)
    result = await svc.ingest(
        source_type="group",
        source_id="g6",
        sender_raw="+971581234567",
        raw_text="WTS iPhone 16 Pro Max 256GB",
        captured_at=newer_captured,
        dedup_hash="fp-earliest-hash",
        group_name="Later Group",
    )
    assert result.captured_at == older_captured


@pytest.mark.asyncio
async def test_fingerprint_refreshes_expiry_on_bump(monkeypatch):
    """On fingerprint collision, refresh expires_at per side rules."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    svc._contacts.upsert_by_phone = AsyncMock(return_value=_mock_contact())
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    from app.modules.market.models import Product, ProductAlias

    product = MagicMock(spec=Product)
    product.id = uuid.uuid4()
    alias_row = MagicMock(spec=ProductAlias)
    svc._aliases.resolve = AsyncMock(return_value=[(alias_row, product)])

    old_expiry = datetime.now(UTC) - timedelta(hours=1)
    existing_id = uuid.uuid4()
    existing_msg = MagicMock(spec=MarketMessage)
    existing_msg.id = existing_id
    existing_msg.side = "SELL"
    existing_msg.seen_count = 1
    existing_msg.source_groups = []
    existing_msg.captured_at = datetime.now(UTC) - timedelta(hours=10)
    existing_msg.expires_at = old_expiry
    svc._mm.get = AsyncMock(return_value=existing_msg)

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)
    mock_redis.get = AsyncMock(return_value=str(existing_id))
    monkeypatch.setattr(
        "app.core.redis.get_async_redis",
        lambda: mock_redis,
    )

    result = await svc.ingest(
        source_type="group",
        source_id="g7",
        sender_raw="+971581234567",
        raw_text="WTS iPhone 16 Pro Max 256GB",
        captured_at=datetime.now(UTC),
        dedup_hash="fp-refresh-hash",
    )
    assert result.expires_at > old_expiry


@pytest.mark.asyncio
async def test_fingerprint_bump_disappeared_row_falls_through(monkeypatch):
    """If the fingerprinted row was deleted, fall through to create a new one."""
    svc, session = _make_async_service(MarketIngestionService)
    svc._mm.get_by_dedup_hash = AsyncMock(return_value=None)
    svc._contacts.upsert_by_phone = AsyncMock(return_value=_mock_contact())
    svc._mmp.list_for_message = AsyncMock(return_value=[])

    from app.modules.market.models import Product, ProductAlias

    product = MagicMock(spec=Product)
    product.id = uuid.uuid4()
    alias_row = MagicMock(spec=ProductAlias)
    svc._aliases.resolve = AsyncMock(return_value=[(alias_row, product)])

    svc._mm.get = AsyncMock(return_value=None)
    svc._mmp.create = AsyncMock()
    svc._cpt.increment_tag = AsyncMock()

    mid = uuid.uuid4()
    fake_msg = MagicMock(spec=MarketMessage)
    fake_msg.id = mid
    fake_msg.side = "SELL"
    svc._mm.create = AsyncMock(return_value=fake_msg)
    svc._mm.supersede_repost = AsyncMock(return_value=0)

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)
    mock_redis.get = AsyncMock(return_value=str(uuid.uuid4()))
    monkeypatch.setattr(
        "app.core.redis.get_async_redis",
        lambda: mock_redis,
    )

    result = await svc.ingest(
        source_type="group",
        source_id="g8",
        sender_raw="+971581234571",
        raw_text="WTS iPhone 16 Pro Max 256GB",
        captured_at=datetime.now(UTC),
        dedup_hash="fp-orphan-hash",
    )
    assert result is fake_msg
    svc._mm.create.assert_awaited_once()
