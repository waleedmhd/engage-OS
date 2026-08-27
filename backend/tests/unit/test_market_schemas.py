"""Unit tests for market module Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.modules.market.schemas import (
    DealCreateRequest,
    DealResponse,
    DealUpdateRequest,
    MarketMessageBatchIngest,
    MarketMessageIngest,
    MarketSearchParams,
    OutreachBatchRequest,
    OutreachSendRequest,
    PrecomputedBlock,
    PrecomputedProduct,
    ProductCreateRequest,
    ProductResponse,
    ProductUpdateRequest,
    SavedSearchCreateRequest,
    SavedSearchResponse,
    SearchEventResponse,
)

# ----------------------------------------------------------------- ingestion


def test_market_message_ingest_valid():
    msg = MarketMessageIngest(
        source_type="group",
        source_id="chat-123",
        sender_raw="+971581234567",
        raw_text="WTS iPhone 16 Pro Max 256GB",
        captured_at=datetime.now(UTC),
        dedup_hash="abc123def456",
    )
    assert msg.source_type == "group"
    assert msg.raw_text == "WTS iPhone 16 Pro Max 256GB"


def test_market_message_ingest_minimal():
    msg = MarketMessageIngest(
        source_type="dm",
        raw_text="hello",
        captured_at=datetime.now(UTC),
        dedup_hash="minimal_hash",
    )
    assert msg.source_id is None
    assert msg.sender_raw is None


def test_market_message_ingest_normalises_whatsapp_prefix():
    """P9 listener sends 'whatsapp_group' but the DB check constraint
    only allows 'group', 'channel', 'dm'."""
    msg = MarketMessageIngest(
        source_type="whatsapp_group",
        raw_text="WTS iPhone",
        captured_at=datetime.now(UTC),
        dedup_hash="hash_wag",
    )
    assert msg.source_type == "group"


def test_market_message_ingest_leaves_canonical_source_type_alone():
    """Canonical values pass through unchanged."""
    for st in ("group", "channel", "dm"):
        msg = MarketMessageIngest(
            source_type=st,
            raw_text="test",
            captured_at=datetime.now(UTC),
            dedup_hash=f"hash_{st}",
        )
        assert msg.source_type == st


def test_market_message_ingest_missing_required():
    with pytest.raises(ValidationError):
        MarketMessageIngest(raw_text="x", captured_at=datetime.now(UTC), dedup_hash="d")


def test_market_message_ingest_empty_text():
    with pytest.raises(ValidationError):
        MarketMessageIngest(
            source_type="group",
            raw_text="",
            captured_at=datetime.now(UTC),
            dedup_hash="hash123",
        )


# ----------------------------------------------------------------- search params


def test_search_params_defaults():
    params = MarketSearchParams()
    assert params.q == ""
    assert params.cursor is None
    assert params.page_size == 50
    assert params.q == ""  # default query is empty


def test_search_params_page_bounds():
    with pytest.raises(ValidationError):
        MarketSearchParams(page_size=0)

    with pytest.raises(ValidationError):
        MarketSearchParams(page_size=201)


def test_search_params_optional_filters():
    params = MarketSearchParams(
        q="iphone 16",
        side="BUY",
        product_ids=[uuid.uuid4(), uuid.uuid4()],
        brand="Apple",
        family="iPhone",
        condition="new",
        grade="A",
    )
    assert params.q == "iphone 16"
    assert params.side == "BUY"
    assert len(params.product_ids) == 2
    assert params.brand == "Apple"
    assert params.family == "iPhone"
    assert params.condition == "new"


# ----------------------------------------------------------------- product schemas


def test_product_create_request():
    p = ProductCreateRequest(
        brand="Apple",
        family="iPhone",
        canonical_name="iphone 17 pro max",
        tier="pro max",
    )
    assert p.is_active is True


def test_product_update_request_partial():
    p = ProductUpdateRequest(brand="Samsung", is_active=False)
    assert p.family is None
    assert p.canonical_name is None


def test_product_response_from_attributes():
    pid = uuid.uuid4()
    now = datetime.now(UTC)
    p = ProductResponse(
        id=pid,
        brand="Apple",
        family="iPhone",
        canonical_name="iphone 16 pro",
        tier="pro",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    assert p.id == pid
    assert p.canonical_name == "iphone 16 pro"


# ----------------------------------------------------------------- saved search schemas


def test_saved_search_create_minimal():
    s = SavedSearchCreateRequest(name="Morning iPhone scan", query_text="iphone 16")
    assert s.resolved_product_ids is None
    assert s.filters is None


def test_saved_search_create_full():
    s = SavedSearchCreateRequest(
        name="Samsung BUY leads",
        query_text="samsung s25",
        resolved_product_ids=[uuid.uuid4()],
        filters={"condition": "new"},
    )
    assert len(s.resolved_product_ids) == 1


def test_saved_search_response():
    uid = uuid.uuid4()
    sid = uuid.uuid4()
    now = datetime.now(UTC)
    s = SavedSearchResponse(
        id=sid,
        user_id=uid,
        name="test",
        query_text="iphone",
        resolved_product_ids=None,
        filters=None,
        created_at=now,
        updated_at=now,
    )
    assert s.id == sid


# ----------------------------------------------------------------- search event schemas


def test_search_event_response():
    now = datetime.now(UTC)
    se = SearchEventResponse(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        query_text="iphone 16",
        resolved_product_ids=None,
        filters=None,
        buy_result_count=5,
        sell_result_count=10,
        executed_at=now,
    )
    assert se.buy_result_count == 5
    assert se.sell_result_count == 10


# ----------------------------------------------------------------- outreach schemas


def test_outreach_send_request():
    o = OutreachSendRequest(
        contact_id=uuid.uuid4(),
        template_id=uuid.uuid4(),
    )
    assert o.search_event_id is None
    assert o.market_message_id is None


def test_outreach_batch_request():
    o = OutreachBatchRequest(
        search_event_id=uuid.uuid4(),
        sends=[
            OutreachSendRequest(contact_id=uuid.uuid4(), template_id=uuid.uuid4()),
            OutreachSendRequest(contact_id=uuid.uuid4(), template_id=uuid.uuid4()),
        ],
    )
    assert len(o.sends) == 2


def test_outreach_batch_request_max_100():
    with pytest.raises(ValidationError):
        OutreachBatchRequest(sends=[])


def test_outreach_batch_request_max_exceeded():
    sends = [
        OutreachSendRequest(contact_id=uuid.uuid4(), template_id=uuid.uuid4())
        for _ in range(101)
    ]
    with pytest.raises(ValidationError):
        OutreachBatchRequest(sends=sends)


# ----------------------------------------------------------------- deal schemas


def test_deal_create_request_minimal():
    d = DealCreateRequest()
    assert d.buyer_contact_id is None
    assert d.product_id is None


def test_deal_update_request():
    d = DealUpdateRequest(status="contacted", qty=5)
    assert d.status == "contacted"
    assert d.target_price is None


def test_deal_response():
    now = datetime.now(UTC)
    d = DealResponse(
        id=uuid.uuid4(),
        buyer_contact_id=None,
        seller_contact_id=None,
        product_id=None,
        qty=None,
        target_price=None,
        status="matched",
        origin_search_event_id=None,
        created_by=None,
        created_at=now,
        updated_at=now,
    )
    assert d.status == "matched"


# ------------------------------------------------------------- batch ingest schemas


def _ingest_item(dedup_hash: str = "abc123") -> dict:
    return {
        "source_type": "group",
        "raw_text": "WTS iPhone 16 Pro Max",
        "captured_at": datetime.now(UTC).isoformat(),
        "dedup_hash": dedup_hash,
    }


def test_batch_ingest_zero_items_validation_error():
    with pytest.raises(ValidationError) as exc:
        MarketMessageBatchIngest(items=[])
    assert "items" in str(exc.value)


def test_batch_ingest_51_items_validation_error():
    with pytest.raises(ValidationError) as exc:
        MarketMessageBatchIngest(items=[MarketMessageIngest(**_ingest_item(f"hash-{i}")) for i in range(51)])
    assert "items" in str(exc.value)


def test_batch_ingest_valid_two_items():
    batch = MarketMessageBatchIngest(
        items=[
            MarketMessageIngest(**_ingest_item("hash-batch-1")),
            MarketMessageIngest(**_ingest_item("hash-batch-2")),
        ]
    )
    assert len(batch.items) == 2


def test_market_message_ingest_precomputed_optional():
    msg = MarketMessageIngest(**_ingest_item("hash-no-pc"))
    assert msg.precomputed is None
    assert msg.group_name is None
    assert msg.sender_name is None
    assert msg.msg_type is None


def test_market_message_ingest_with_precomputed():
    msg = MarketMessageIngest(
        **_ingest_item("hash-with-pc"),
        precomputed=PrecomputedBlock(
            version="listener-v0.3",
            side="SELL",
            products=[
                PrecomputedProduct(
                    hint="16pm",
                    qty=2,
                    unit_price=3500.00,
                    currency="AED",
                    storage="256GB",
                    color="black",
                    condition="new",
                    grade="A",
                )
            ],
        ),
    )
    assert msg.precomputed is not None
    assert msg.precomputed.version == "listener-v0.3"
    assert msg.precomputed.side == "SELL"
    assert len(msg.precomputed.products) == 1
    assert msg.precomputed.products[0].hint == "16pm"
    assert msg.precomputed.products[0].qty == 2


def test_market_message_ingest_with_metadata():
    msg = MarketMessageIngest(
        **_ingest_item("hash-meta"),
        group_name="Dubai Phones Marketplace",
        sender_name="Ahmed Trader",
        msg_type="text",
    )
    assert msg.group_name == "Dubai Phones Marketplace"
    assert msg.sender_name == "Ahmed Trader"
    assert msg.msg_type == "text"


def test_precomputed_product_minimal():
    pp = PrecomputedProduct(hint="16pm")
    assert pp.hint == "16pm"
    assert pp.qty is None
    assert pp.unit_price is None


def test_precomputed_block_empty_products():
    block = PrecomputedBlock(version="listener-v0.3", side="BUY")
    assert block.products == []
    assert block.attributes is None
    assert block.risk_tags is None
