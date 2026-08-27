"""Integration tests for Phase 12 — Contact Intelligence + Backfill."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.core.security import create_access_token
from app.modules.market.models import (
    ContactProductTag,
    MarketMessage,
    MarketMessageProduct,
    Product,
)
from tests.factories import make_contact, make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


def _seed_product(session, canonical_name: str, brand: str = "Apple") -> Product:
    p = Product(
        id=uuid.uuid4(),
        brand=brand,
        family="Phone",
        canonical_name=canonical_name,
        tier="pro",
        is_active=True,
    )
    session.add(p)
    session.flush()
    return p


def _seed_message(
    session,
    *,
    contact_id: uuid.UUID,
    raw_text: str,
    side: str = "BUY",
    extracted_attributes: dict | None = None,
    unit_price: float | None = None,
    currency: str | None = "AED",
    product_id: uuid.UUID | None = None,
) -> MarketMessage:
    now = datetime.now(tz=UTC)
    msg = MarketMessage(
        id=uuid.uuid4(),
        source_type="group",
        source_id="chat-test",
        sender_raw="+971501234567",
        contact_id=contact_id,
        side=side,
        raw_text=raw_text,
        normalized_text=raw_text.lower(),
        captured_at=now,
        expires_at=now + timedelta(hours=48),
        status="ACTIVE",
        review_status="AUTO",
        dedup_hash=f"ci-test-{uuid.uuid4().hex[:12]}",
        extracted_attributes=(
            sa.null() if extracted_attributes is None else extracted_attributes
        ),
    )
    session.add(msg)
    session.flush()

    if product_id:
        mmp = MarketMessageProduct(
            id=uuid.uuid4(),
            market_message_id=msg.id,
            product_id=product_id,
            unit_price=unit_price,
            currency=currency,
            confidence=0.9,
            resolver="keyword",
        )
        session.add(mmp)
        session.flush()

    return msg


def _seed_tag(session, contact_id: uuid.UUID, product_id: uuid.UUID, buy: int = 0, sell: int = 0) -> None:
    now = datetime.now(tz=UTC)
    tag = ContactProductTag(
        contact_id=contact_id,
        product_id=product_id,
        side_buy_count=buy,
        side_sell_count=sell,
        observation_count=buy + sell,
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(tag)
    session.flush()


# ---------------------------------------------------------------------- intelligence endpoint


@pytest.mark.asyncio
async def test_intelligence_buy_messages(committed_db, client):
    """Contact with 5 buy messages for iPhone → intelligence shows buy_messages: 5, products include iPhone."""
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db, name="Buyer One")
    iphone = _seed_product(committed_db, "iPhone 16 Pro Max")

    for i in range(5):
        _seed_message(
            committed_db,
            contact_id=contact.id,
            raw_text=f"WTB iPhone 16 Pro Max 256GB #{i}",
            side="BUY",
            product_id=iphone.id,
            unit_price=1200.0 + i * 50,
        )
    _seed_tag(committed_db, contact.id, iphone.id, buy=5)
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/market/contacts/{contact.id}/intelligence",
        headers=_token(admin),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["buy_messages"] == 5
    assert data["sell_messages"] == 0
    assert data["total_messages"] == 5
    assert data["contact_name"] == "Buyer One"
    assert len(data["products"]) == 1
    assert data["products"][0]["product_name"] == "iPhone 16 Pro Max"
    assert data["products"][0]["buy_count"] == 5
    assert data["price_range"]["currency"] == "AED"
    assert data["price_range"]["min_unit_price"] is not None
    assert data["price_range"]["max_unit_price"] is not None


@pytest.mark.asyncio
async def test_intelligence_mixed_buy_sell(committed_db, client):
    """Contact with mixed buy/sell → counts are separated."""
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db, name="Trader")
    iphone = _seed_product(committed_db, "iPhone 16 Pro Max")

    _seed_message(committed_db, contact_id=contact.id, raw_text="WTB iPhone", side="BUY", product_id=iphone.id)
    _seed_message(committed_db, contact_id=contact.id, raw_text="WTB iPhone again", side="BUY", product_id=iphone.id)
    _seed_message(committed_db, contact_id=contact.id, raw_text="WTS iPhone sealed", side="SELL", product_id=iphone.id)
    _seed_tag(committed_db, contact.id, iphone.id, buy=2, sell=1)
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/market/contacts/{contact.id}/intelligence",
        headers=_token(admin),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["buy_messages"] == 2
    assert data["sell_messages"] == 1
    assert data["total_messages"] == 3


@pytest.mark.asyncio
async def test_intelligence_attribute_preferences(committed_db, client):
    """Contact with extracted_attributes containing storage/color → attribute_preferences aggregates them."""
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db, name="Spec Hunter")
    iphone = _seed_product(committed_db, "iPhone 16 Pro Max")

    _seed_message(
        committed_db,
        contact_id=contact.id,
        raw_text="WTB iPhone 256GB black",
        side="BUY",
        product_id=iphone.id,
        extracted_attributes={
            "intent": {"side": "buy"},
            "attributes": {
                "passed": True,
                "brand": "apple",
                "storage": ["256GB"],
                "color": ["Black"],
                "condition": ["COND_NEW"],
            },
        },
    )
    _seed_message(
        committed_db,
        contact_id=contact.id,
        raw_text="WTB iPhone 512GB white",
        side="BUY",
        product_id=iphone.id,
        extracted_attributes={
            "intent": {"side": "buy"},
            "attributes": {
                "passed": True,
                "brand": "apple",
                "storage": ["512GB"],
                "color": ["White"],
                "region": ["REGION_UAE"],
            },
        },
    )
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/market/contacts/{contact.id}/intelligence",
        headers=_token(admin),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    prefs = data["attribute_preferences"]
    assert len(prefs["storage"]) == 2
    assert {"value": "256GB", "count": 1} in prefs["storage"]
    assert {"value": "512GB", "count": 1} in prefs["storage"]
    assert len(prefs["color"]) == 2
    assert len(prefs["region"]) == 1
    assert len(prefs["condition"]) == 1


@pytest.mark.asyncio
async def test_intelligence_zero_messages(committed_db, client):
    """Contact with zero market messages → returns empty profile, not 500."""
    admin = make_user(committed_db, role="admin")
    contact = make_contact(committed_db, name="Ghost")

    committed_db.commit()

    resp = await client.get(
        f"/api/v1/market/contacts/{contact.id}/intelligence",
        headers=_token(admin),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_messages"] == 0
    assert data["buy_messages"] == 0
    assert data["sell_messages"] == 0
    assert data["products"] == []
    assert data["active_since"] is None
    assert data["last_active"] is None


@pytest.mark.asyncio
async def test_intelligence_requires_auth(client):
    """Intelligence endpoint rejects unauthenticated requests."""
    resp = await client.get(f"/api/v1/market/contacts/{uuid.uuid4()}/intelligence")
    assert resp.status_code == 401


# ---------------------------------------------------------------------- contacts ranked


@pytest.mark.asyncio
async def test_contacts_ranked_by_buy(committed_db, client):
    """GET /contacts/ranked?side=BUY returns contacts ordered by buy count."""
    admin = make_user(committed_db, role="admin")
    c1 = make_contact(committed_db, name="Heavy Buyer")
    c2 = make_contact(committed_db, name="Light Buyer")
    iphone = _seed_product(committed_db, "iPhone 16 Pro Max")

    for _ in range(5):
        _seed_message(committed_db, contact_id=c1.id, raw_text="WTB iPhone", side="BUY", product_id=iphone.id)
    for _ in range(2):
        _seed_message(committed_db, contact_id=c2.id, raw_text="WTB iPhone", side="BUY", product_id=iphone.id)
    _seed_tag(committed_db, c1.id, iphone.id, buy=5)
    _seed_tag(committed_db, c2.id, iphone.id, buy=2)
    committed_db.commit()

    resp = await client.get(
        "/api/v1/market/contacts/ranked?side=BUY&limit=10",
        headers=_token(admin),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = [r["contact_id"] for r in data]
    assert str(c1.id) in ids
    assert str(c2.id) in ids
    assert ids.index(str(c1.id)) < ids.index(str(c2.id))  # c1 (5 buys) before c2 (2 buys)


@pytest.mark.asyncio
async def test_contacts_ranked_by_product(committed_db, client):
    """GET /contacts/ranked?product_id=X filters by product."""
    admin = make_user(committed_db, role="admin")
    c1 = make_contact(committed_db, name="iPhone Guy")
    c2 = make_contact(committed_db, name="Samsung Guy")
    iphone = _seed_product(committed_db, "iPhone 16 Pro Max")
    samsung = _seed_product(committed_db, "Galaxy S25 Ultra", brand="Samsung")

    _seed_message(committed_db, contact_id=c1.id, raw_text="WTB iPhone", side="BUY", product_id=iphone.id)
    _seed_message(committed_db, contact_id=c2.id, raw_text="WTB Samsung", side="BUY", product_id=samsung.id)
    _seed_tag(committed_db, c1.id, iphone.id, buy=1)
    _seed_tag(committed_db, c2.id, samsung.id, buy=1)
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/market/contacts/ranked?product_id={iphone.id}&limit=10",
        headers=_token(admin),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = [r["contact_id"] for r in data]
    assert str(c1.id) in ids
    assert str(c2.id) not in ids


# ---------------------------------------------------------------------- backfill task


@pytest.mark.asyncio
async def test_backfill_populates_extracted_attributes(committed_db):
    """Backfill task populates extracted_attributes on messages that lack it."""
    contact = make_contact(committed_db)
    _seed_message(
        committed_db,
        contact_id=contact.id,
        raw_text="WTB iPhone 16 Pro Max 256GB Black",
        side="BUY",
        extracted_attributes=None,  # Not yet populated
    )
    committed_db.commit()

    from app.modules.market.tasks import backfill_extracted_attributes_task

    result = backfill_extracted_attributes_task(batch_size=200)
    assert result["backfilled"] >= 1

    # Verify the row now has extracted_attributes.
    from sqlalchemy import select

    msg = committed_db.execute(
        select(MarketMessage).where(MarketMessage.contact_id == contact.id).limit(1)
    ).scalar_one()
    assert msg.extracted_attributes is not None
    assert "intent" in msg.extracted_attributes
    assert "attributes" in msg.extracted_attributes
    assert msg.extracted_attributes.get("intent", {}).get("side") == "buy"


@pytest.mark.asyncio
async def test_backfill_is_idempotent(committed_db):
    """Backfill running twice doesn't overwrite already-populated rows."""
    contact = make_contact(committed_db)
    _seed_message(
        committed_db,
        contact_id=contact.id,
        raw_text="WTB iPhone 16 Pro Max 256GB Black",
        side="BUY",
        extracted_attributes=None,
    )
    committed_db.commit()

    from app.modules.market.tasks import backfill_extracted_attributes_task

    # First run populates it.
    result1 = backfill_extracted_attributes_task(batch_size=200)
    assert result1["backfilled"] >= 1

    # Second run should skip it (0 backfilled).
    result2 = backfill_extracted_attributes_task(batch_size=200)
    assert result2["backfilled"] == 0


@pytest.mark.asyncio
async def test_backfill_skips_already_populated(committed_db):
    """Backfill only touches rows where extracted_attributes is NULL."""
    contact = make_contact(committed_db)
    _seed_message(
        committed_db,
        contact_id=contact.id,
        raw_text="WTS Samsung Galaxy S25",
        side="SELL",
        extracted_attributes={"already": "populated"},
    )
    committed_db.commit()

    from app.modules.market.tasks import backfill_extracted_attributes_task

    result = backfill_extracted_attributes_task(batch_size=200)
    assert result["backfilled"] == 0
