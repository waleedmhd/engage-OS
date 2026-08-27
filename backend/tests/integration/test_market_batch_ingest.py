"""Integration tests for POST /market/messages/batch — P1 ingest contract v2."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.core.security import create_access_token
from app.modules.market.models import (
    MarketMessage,
    MarketMessageProduct,
    Product,
    ProductAlias,
)
from tests.factories import make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


def _seed_product(session, canonical_name: str, brand: str = "Apple", family: str = "iPhone") -> Product:
    p = Product(
        id=uuid.uuid4(),
        brand=brand,
        family=family,
        canonical_name=canonical_name,
        tier="pro",
        is_active=True,
    )
    session.add(p)
    session.flush()
    return p


def _seed_alias(session, product_id: uuid.UUID, alias: str, source: str = "seed") -> ProductAlias:
    a = ProductAlias(
        id=uuid.uuid4(),
        product_id=product_id,
        alias=alias,
        source=source,
    )
    session.add(a)
    session.flush()
    return a


def _batch_payload(*items: dict) -> dict:
    return {"items": list(items)}


def _ingest_item(
    raw_text: str,
    dedup_hash: str,
    *,
    source_type: str = "group",
    sender_raw: str | None = "+971581234567",
    precomputed: dict | None = None,
    group_name: str | None = None,
    sender_name: str | None = None,
    msg_type: str | None = None,
) -> dict:
    return {
        "source_type": source_type,
        "source_id": "chat-123",
        "sender_raw": sender_raw,
        "raw_text": raw_text,
        "captured_at": datetime.now(UTC).isoformat(),
        "dedup_hash": dedup_hash,
        "group_name": group_name,
        "sender_name": sender_name,
        "msg_type": msg_type,
        "precomputed": precomputed,
    }


# ---------------------------------------------------------------------- idempotency


@pytest.mark.asyncio
async def test_batch_idempotency_replay_same_payload_row_counts_unchanged(
    committed_db, client
):
    """Replaying the same batch produces no new rows — exact count match."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _batch_payload(
        _ingest_item("WTS iPhone 16 Pro Max 256GB", "hash-idem-001"),
        _ingest_item("WTB Samsung S25 Ultra", "hash-idem-002"),
    )

    # First call — creates both.
    resp = await client.post("/api/v1/market/messages/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 2
    assert all(r["status"] == "created" for r in body)

    first_count = committed_db.execute(
        select(text("count(*)")).select_from(MarketMessage)
    ).scalar_one()

    # Second call — all duplicates.
    resp = await client.post("/api/v1/market/messages/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 2
    assert all(r["status"] == "duplicate" for r in body)

    second_count = committed_db.execute(
        select(text("count(*)")).select_from(MarketMessage)
    ).scalar_one()
    assert second_count == first_count


@pytest.mark.asyncio
async def test_batch_duplicate_within_batch_detected(committed_db, client):
    """Two items with the same dedup_hash in one batch — second is duplicate."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _batch_payload(
        _ingest_item("WTS iPhone 16", "hash-same-batch"),
        _ingest_item("WTB Samsung S25", "hash-same-batch"),  # same hash
    )

    resp = await client.post("/api/v1/market/messages/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 2
    assert body[0]["status"] == "created"
    assert body[1]["status"] == "duplicate"

    count = committed_db.execute(
        select(text("count(*)")).select_from(MarketMessage)
    ).scalar_one()
    assert count == 1


# --------------------------------------------------------------- precomputed trust path


@pytest.mark.asyncio
async def test_precomputed_side_and_products_applied_verbatim(committed_db, client):
    """With trust flag on, precomputed block overrides side and resolves products."""
    admin = make_user(committed_db, role="admin")
    # Seed a product + alias so the precomputed hint can resolve.
    prod = _seed_product(committed_db, "iphone 16 pro max")
    _seed_alias(committed_db, prod.id, "16pm")
    committed_db.commit()
    h = _token(admin)

    payload = _batch_payload(
        _ingest_item(
            "some text that would classify as BUY due to 'need'",
            "hash-pc-001",
            precomputed={
                "version": "listener-v0.3",
                "side": "SELL",
                "attributes": {"source": "precomputed"},
                "products": [
                    {
                        "hint": "16pm",
                        "qty": 2,
                        "unit_price": "3500.00",
                        "currency": "AED",
                        "storage": "256GB",
                        "color": "black",
                        "condition": "new",
                        "grade": "A",
                    }
                ],
                "risk_tags": [],
            },
        )
    )

    resp = await client.post("/api/v1/market/messages/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["status"] == "created"
    msg_id = body[0]["message_id"]

    # Verify the message has side=SELL (from precomputed, not keyword).
    msg = committed_db.execute(
        select(MarketMessage).where(MarketMessage.id == msg_id)
    ).scalar_one()
    assert msg.side == "SELL"

    # Verify product resolution.
    mmp = committed_db.execute(
        select(MarketMessageProduct).where(
            MarketMessageProduct.market_message_id == msg_id
        )
    ).scalar_one()
    assert mmp.product_id == prod.id
    assert mmp.qty == 2
    assert float(mmp.unit_price) == 3500.00  # type: ignore[arg-type]
    assert mmp.currency == "AED"
    assert mmp.color == "black"
    assert mmp.condition == "new"
    assert mmp.grade == "A"
    assert mmp.side == "SELL"
    assert mmp.attributes is not None
    assert mmp.attributes["storage"] == "256GB"
    assert mmp.attributes["source"] == "precomputed"


@pytest.mark.asyncio
async def test_precomputed_group_and_sender_metadata_persisted(committed_db, client):
    """group_name, sender_name, msg_type from the listener are stored."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _batch_payload(
        _ingest_item(
            "WTS iPhone",
            "hash-meta-001",
            group_name="Dubai Phones Marketplace",
            sender_name="Ahmed Trader",
            msg_type="text",
        )
    )

    resp = await client.post("/api/v1/market/messages/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    msg_id = body[0]["message_id"]

    msg = committed_db.execute(
        select(MarketMessage).where(MarketMessage.id == msg_id)
    ).scalar_one()
    assert msg.group_name == "Dubai Phones Marketplace"
    assert msg.sender_name == "Ahmed Trader"
    assert msg.msg_type == "text"


# ------------------------------------------------------------ old keyword path still works


@pytest.mark.asyncio
async def test_message_without_precomputed_follows_keyword_path(committed_db, client):
    """A message sent without a precomputed block uses the keyword classifier."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    _seed_alias(committed_db, prod.id, "iphone 16 pro max")
    committed_db.commit()
    h = _token(admin)

    payload = _batch_payload(
        _ingest_item(
            "WTS iPhone 16 Pro Max 256GB new sealed",
            "hash-kw-001",
            precomputed=None,
        )
    )

    resp = await client.post("/api/v1/market/messages/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body[0]["status"] == "created"
    msg_id = body[0]["message_id"]

    msg = committed_db.execute(
        select(MarketMessage).where(MarketMessage.id == msg_id)
    ).scalar_one()
    # "WTS" matches SELL pattern.
    assert msg.side == "SELL"

    mmp = committed_db.execute(
        select(MarketMessageProduct).where(
            MarketMessageProduct.market_message_id == msg_id
        )
    ).scalar_one()
    assert mmp.product_id == prod.id


# ------------------------------------------------------ unresolvable hints don't fail


@pytest.mark.asyncio
async def test_unresolvable_precomputed_hints_do_not_fail_item(committed_db, client):
    """A precomputed hint with no matching alias is skipped; the item still ingests."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _batch_payload(
        _ingest_item(
            "any random marketplace text",
            "hash-unres-001",
            precomputed={
                "version": "listener-v0.3",
                "side": "SELL",
                "attributes": {},
                "products": [
                    {"hint": "nonexistent-product-hint", "qty": 1},
                ],
                "risk_tags": [],
            },
        )
    )

    resp = await client.post("/api/v1/market/messages/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body[0]["status"] == "created"
    msg_id = body[0]["message_id"]

    # Message exists with precomputed side applied.
    msg = committed_db.execute(
        select(MarketMessage).where(MarketMessage.id == msg_id)
    ).scalar_one()
    assert msg.side == "SELL"

    # No product resolutions (hint unresolvable).
    count = committed_db.execute(
        select(text("count(*)")).select_from(MarketMessageProduct).where(
            MarketMessageProduct.market_message_id == msg_id
        )
    ).scalar_one()
    assert count == 0


# ------------------------------------------------------------- mixed batch


@pytest.mark.asyncio
async def test_batch_mixed_new_and_duplicate(committed_db, client):
    """One fresh item + one already-ingested hash — mixed statuses, no failures."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    # First, ingest one item to create a "pre-existing" hash.
    first = _batch_payload(_ingest_item("WTS iPhone 16", "hash-mixed-001"))
    resp = await client.post("/api/v1/market/messages/batch", json=first, headers=h)
    assert resp.status_code == 201

    # Now send a batch with the same hash + a new one.
    mixed = _batch_payload(
        _ingest_item("WTS iPhone 16", "hash-mixed-001"),  # duplicate
        _ingest_item("WTB Samsung S25", "hash-mixed-002"),  # new
    )
    resp = await client.post("/api/v1/market/messages/batch", json=mixed, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 2
    assert body[0]["status"] == "duplicate"
    assert body[1]["status"] == "created"
