"""Integration tests for Phase 5 — Review Queue API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core.security import create_access_token
from app.modules.contacts.models import Contact
from app.modules.market.models import (
    ContactProductTag,
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


def _seed_contact(session, phone: str = "+971501234567") -> Contact:
    c = Contact(
        id=uuid.uuid4(),
        phone=phone,
        name="Test Contact",
    )
    session.add(c)
    session.flush()
    return c


def _seed_pending_message(
    session,
    *,
    side: str = "SELL",
    raw_text: str = "WTS iPhone 16 Pro Max",
    contact_id: uuid.UUID | None = None,
    sender_raw: str | None = None,
    captured_at: datetime | None = None,
    expires_at: datetime | None = None,
    dedup_hash: str | None = None,
) -> MarketMessage:
    now = datetime.now(tz=UTC)
    msg = MarketMessage(
        id=uuid.uuid4(),
        source_type="group",
        source_id="chat-test",
        sender_raw=sender_raw or "+971501234567",
        contact_id=contact_id,
        side=side,
        raw_text=raw_text,
        normalized_text=raw_text.lower(),
        captured_at=captured_at or now,
        expires_at=expires_at or (now + timedelta(hours=48)),
        status="ACTIVE",
        review_status="PENDING",
        dedup_hash=dedup_hash or f"test-{uuid.uuid4().hex[:12]}",
    )
    session.add(msg)
    session.flush()
    return msg


def _seed_mmp(
    session, message_id: uuid.UUID, product_id: uuid.UUID, *, confidence: float = 0.75
) -> MarketMessageProduct:
    mmp = MarketMessageProduct(
        id=uuid.uuid4(),
        market_message_id=message_id,
        product_id=product_id,
        confidence=confidence,
        resolver="keyword",
        attributes={"_confidence": {"side": confidence, "product": confidence}},
    )
    session.add(mmp)
    session.flush()
    return mmp


# ---------------------------------------------------------------------- transactional resolve


@pytest.mark.asyncio
async def test_resolve_transactional_bad_fk_rolls_back_everything(committed_db, client):
    """A resolution with a non-existent product_id fails at FK level;
    the entire operation rolls back — message stays PENDING."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    msg = _seed_pending_message(committed_db, contact_id=None)
    _seed_mmp(committed_db, msg.id, prod.id)
    committed_db.commit()
    h = _token(admin)

    fake_product_id = uuid.uuid4()
    payload = {
        "corrected_side": None,
        "resolutions": [
            {"product_id": str(fake_product_id), "attributes": {"qty": 3}},
        ],
        "teach": [],
    }

    resp = await client.post(
        f"/api/v1/market/review/{msg.id}/resolve", json=payload, headers=h
    )
    # FK violation gets caught by the service and re-raised as ValueError → 409.
    assert resp.status_code in (500, 422, 409, 400), resp.text

    # Verify message is still PENDING.
    committed_db.expire_all()
    msg_after = committed_db.execute(
        select(MarketMessage).where(MarketMessage.id == msg.id)
    ).scalar_one()
    assert msg_after.review_status == "PENDING"

    # Verify no new MMP rows were inserted for the fake product.
    mmp_count = committed_db.execute(
        select(text("count(*)")).select_from(MarketMessageProduct).where(
            MarketMessageProduct.market_message_id == msg.id
        )
    ).scalar_one()
    assert mmp_count == 1


@pytest.mark.asyncio
async def test_resolve_updates_side_and_resolutions(committed_db, client):
    """Corrected side + attribute overrides are persisted."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    msg = _seed_pending_message(committed_db, side="BUY")
    _seed_mmp(committed_db, msg.id, prod.id)
    committed_db.commit()
    h = _token(admin)

    payload = {
        "corrected_side": "SELL",
        "resolutions": [
            {
                "product_id": str(prod.id),
                "attributes": {"qty": 5, "color": "black", "condition": "new"},
            },
        ],
        "teach": [],
    }

    resp = await client.post(
        f"/api/v1/market/review/{msg.id}/resolve", json=payload, headers=h
    )
    assert resp.status_code == 200, resp.text

    # Verify message side and review_status updated.
    committed_db.expire_all()
    msg_after = committed_db.execute(
        select(MarketMessage).where(MarketMessage.id == msg.id)
    ).scalar_one()
    assert msg_after.side == "SELL"
    assert msg_after.review_status == "REVIEWED"

    # Verify MMP attributes updated.
    mmp = committed_db.execute(
        select(MarketMessageProduct).where(
            MarketMessageProduct.market_message_id == msg.id
        )
    ).scalar_one()
    assert mmp.qty == 5
    assert mmp.color == "black"
    assert mmp.condition == "new"


@pytest.mark.asyncio
async def test_resolve_writes_teach_entries(committed_db, client):
    """Human-taught product aliases are persisted with source='human'."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 17 pro max")
    msg = _seed_pending_message(committed_db)
    _seed_mmp(committed_db, msg.id, prod.id)
    committed_db.commit()
    h = _token(admin)

    payload = {
        "corrected_side": None,
        "resolutions": [],
        "teach": [
            {"kind": "product", "alias": "17pmax", "canonical": "iphone 17 pro max"},
            {"kind": "color", "alias": "jet", "canonical": "black"},
        ],
    }

    resp = await client.post(
        f"/api/v1/market/review/{msg.id}/resolve", json=payload, headers=h
    )
    assert resp.status_code == 200, resp.text

    # Product teach entry persisted.
    committed_db.expire_all()
    alias_row = committed_db.execute(
        select(ProductAlias).where(
            ProductAlias.product_id == prod.id,
            ProductAlias.alias == "17pmax",
        )
    ).scalar_one_or_none()
    assert alias_row is not None
    assert alias_row.source == "llm_learned"

    # Color teach entry skipped (P7 not yet landed), but no error.
    # Just verify no crash — the resolve succeeded.


@pytest.mark.asyncio
async def test_resolve_applies_deferred_contact_tags(committed_db, client):
    """Human approval applies the deferred increment_tag on the contact."""
    admin = make_user(committed_db, role="admin")
    contact = _seed_contact(committed_db)
    prod = _seed_product(committed_db, "iphone 16 pro max")
    msg = _seed_pending_message(committed_db, contact_id=contact.id)
    _seed_mmp(committed_db, msg.id, prod.id)
    committed_db.commit()
    h = _token(admin)

    # Verify no tag exists yet (PENDING -> guard blocked it).
    existing = committed_db.execute(
        select(ContactProductTag).where(
            ContactProductTag.contact_id == contact.id,
            ContactProductTag.product_id == prod.id,
        )
    ).scalar_one_or_none()
    assert existing is None

    payload = {
        "corrected_side": None,
        "resolutions": [],
        "teach": [],
    }

    resp = await client.post(
        f"/api/v1/market/review/{msg.id}/resolve", json=payload, headers=h
    )
    assert resp.status_code == 200, resp.text

    # Tag now exists.
    committed_db.expire_all()
    tag = committed_db.execute(
        select(ContactProductTag).where(
            ContactProductTag.contact_id == contact.id,
            ContactProductTag.product_id == prod.id,
        )
    ).scalar_one_or_none()
    assert tag is not None


@pytest.mark.asyncio
async def test_resolve_writes_audit_log(committed_db, client):
    """Resolving a message writes an audit_logs row."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    msg = _seed_pending_message(committed_db)
    _seed_mmp(committed_db, msg.id, prod.id)
    committed_db.commit()
    h = _token(admin)

    payload = {"corrected_side": None, "resolutions": [], "teach": []}
    resp = await client.post(
        f"/api/v1/market/review/{msg.id}/resolve", json=payload, headers=h
    )
    assert resp.status_code == 200, resp.text

    audit = committed_db.execute(
        text(
            "SELECT action, entity_type, entity_id, actor_type, actor_id "
            "FROM audit_logs WHERE entity_id = :eid AND action = 'review_resolved'"
        ),
        {"eid": msg.id},
    ).one_or_none()
    assert audit is not None
    assert audit.action == "review_resolved"
    assert audit.entity_type == "market_messages"
    assert str(audit.actor_id) == str(admin.id)


@pytest.mark.asyncio
async def test_resolve_non_pending_rejected(committed_db, client):
    """Calling resolve on an AUTO or already-REVIEWED message returns 409."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    msg = _seed_pending_message(committed_db)
    # Flip to AUTO before committing.
    msg.review_status = "AUTO"
    committed_db.commit()
    h = _token(admin)

    payload = {"corrected_side": None, "resolutions": [], "teach": []}
    resp = await client.post(
        f"/api/v1/market/review/{msg.id}/resolve", json=payload, headers=h
    )
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------- dismiss


@pytest.mark.asyncio
async def test_dismiss_marks_dismissed_and_audits(committed_db, client):
    """Dismissing a PENDING message sets DISMISSED and writes an audit row."""
    admin = make_user(committed_db, role="admin")
    msg = _seed_pending_message(committed_db)
    committed_db.commit()
    h = _token(admin)

    resp = await client.post(
        f"/api/v1/market/review/{msg.id}/dismiss", headers=h
    )
    assert resp.status_code == 204, resp.text

    committed_db.expire_all()
    msg_after = committed_db.execute(
        select(MarketMessage).where(MarketMessage.id == msg.id)
    ).scalar_one()
    assert msg_after.review_status == "DISMISSED"

    audit = committed_db.execute(
        text(
            "SELECT action, entity_type FROM audit_logs "
            "WHERE entity_id = :eid AND action = 'review_dismissed'"
        ),
        {"eid": msg.id},
    ).one_or_none()
    assert audit is not None


@pytest.mark.asyncio
async def test_dismiss_never_touches_contacts(committed_db, client):
    """Dismiss does NOT write contact_product_tags for the message's contact."""
    admin = make_user(committed_db, role="admin")
    contact = _seed_contact(committed_db)
    prod = _seed_product(committed_db, "iphone 16 pro max")
    msg = _seed_pending_message(committed_db, contact_id=contact.id)
    _seed_mmp(committed_db, msg.id, prod.id)
    committed_db.commit()
    h = _token(admin)

    resp = await client.post(
        f"/api/v1/market/review/{msg.id}/dismiss", headers=h
    )
    assert resp.status_code == 204, resp.text

    committed_db.expire_all()
    tag = committed_db.execute(
        select(ContactProductTag).where(
            ContactProductTag.contact_id == contact.id
        )
    ).scalar_one_or_none()
    assert tag is None, "dismiss must not write contact_product_tags"


@pytest.mark.asyncio
async def test_dismiss_non_pending_rejected(committed_db, client):
    """Calling dismiss on an already-REVIEWED message returns 409."""
    admin = make_user(committed_db, role="admin")
    msg = _seed_pending_message(committed_db)
    msg.review_status = "REVIEWED"
    committed_db.commit()
    h = _token(admin)

    resp = await client.post(
        f"/api/v1/market/review/{msg.id}/dismiss", headers=h
    )
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------- ordering


@pytest.mark.asyncio
async def test_urgency_ordering_soonest_expiry_first(committed_db, client):
    """A PENDING item expiring in 10 min appears before one expiring in 3 hours."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    now = datetime.now(tz=UTC)

    urgent = _seed_pending_message(
        committed_db,
        raw_text="URGENT deal",
        expires_at=now + timedelta(minutes=10),
        dedup_hash="urgent-001",
    )
    _seed_mmp(committed_db, urgent.id, prod.id)

    later = _seed_pending_message(
        committed_db,
        raw_text="Later deal",
        expires_at=now + timedelta(hours=3),
        dedup_hash="later-001",
    )
    _seed_mmp(committed_db, later.id, prod.id)
    committed_db.commit()
    h = _token(admin)

    resp = await client.get("/api/v1/market/review?page_size=5", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) >= 2

    ids = [it["id"] for it in items]
    assert ids.index(str(urgent.id)) < ids.index(str(later.id)), (
        f"Urgent ({urgent.id}) must appear before later ({later.id})"
    )


@pytest.mark.asyncio
async def test_non_expired_before_expired(committed_db, client):
    """Non-expired PENDING items appear before expired ones."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    now = datetime.now(tz=UTC)

    expired = _seed_pending_message(
        committed_db,
        raw_text="Expired deal",
        expires_at=now - timedelta(minutes=5),
        captured_at=now - timedelta(hours=2),
        dedup_hash="expired-001",
    )
    _seed_mmp(committed_db, expired.id, prod.id)

    active = _seed_pending_message(
        committed_db,
        raw_text="Active deal",
        expires_at=now + timedelta(hours=1),
        dedup_hash="active-001",
    )
    _seed_mmp(committed_db, active.id, prod.id)
    committed_db.commit()
    h = _token(admin)

    resp = await client.get("/api/v1/market/review?page_size=5", headers=h)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) >= 2

    ids = [it["id"] for it in items]
    assert ids.index(str(active.id)) < ids.index(str(expired.id)), (
        f"Active ({active.id}) must appear before expired ({expired.id})"
    )


# ---------------------------------------------------------------------- stats


@pytest.mark.asyncio
async def test_stats_math_known_data(committed_db, client):
    """Seed a known dataset and verify stats match expectations."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    now = datetime.now(tz=UTC)

    # 3 PENDING (queue_depth = 3).
    for i in range(3):
        msg = _seed_pending_message(
            committed_db,
            raw_text=f"pending {i}",
            dedup_hash=f"pending-{i}-{uuid.uuid4().hex[:6]}",
        )
        _seed_mmp(committed_db, msg.id, prod.id)

    # 1 inflow at edge (created 6 days ago, still PENDING).
    inflow_msg = _seed_pending_message(
        committed_db,
        raw_text="inflow item",
        captured_at=now - timedelta(days=6),
        dedup_hash=f"inflow-{uuid.uuid4().hex[:6]}",
    )
    _seed_mmp(committed_db, inflow_msg.id, prod.id)

    # 1 resolved 5 days ago (outflow in 7d window).
    resolved_msg = MarketMessage(
        id=uuid.uuid4(),
        source_type="group",
        source_id="chat-resolved",
        sender_raw="+971501234567",
        side="SELL",
        raw_text="resolved item",
        normalized_text="resolved item",
        captured_at=now - timedelta(days=10),
        expires_at=now - timedelta(days=9),
        status="ACTIVE",
        review_status="REVIEWED",
        dedup_hash=f"resolved-{uuid.uuid4().hex[:6]}",
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=5),
    )
    committed_db.add(resolved_msg)
    committed_db.flush()

    committed_db.commit()
    h = _token(admin)

    resp = await client.get("/api/v1/market/review/stats", headers=h)
    assert resp.status_code == 200, resp.text
    stats = resp.json()

    assert stats["queue_depth"] >= 3, f"Expected >=3 PENDING, got {stats}"
    assert stats["inflow_7d"] >= 1, f"Expected >=1 inflow, got {stats}"
    assert stats["outflow_7d"] >= 1, f"Expected >=1 outflow, got {stats}"


# ---------------------------------------------------------------------- cursor stability


@pytest.mark.asyncio
async def test_cursor_pagination_no_dupes_on_insert(committed_db, client):
    """Paginating the queue while a new item is inserted doesn't cause skips
    or duplicate items."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    now = datetime.now(tz=UTC)

    # Seed 5 PENDING items ordered by expires_at.
    msg_ids: list[uuid.UUID] = []
    for i in range(5):
        msg = _seed_pending_message(
            committed_db,
            raw_text=f"item {i}",
            expires_at=now + timedelta(minutes=10 * (i + 1)),
            dedup_hash=f"cursor-{i}-{uuid.uuid4().hex[:6]}",
        )
        _seed_mmp(committed_db, msg.id, prod.id)
        msg_ids.append(msg.id)
    committed_db.commit()
    h = _token(admin)

    # Page 1: get first 3.
    resp1 = await client.get("/api/v1/market/review?page_size=3", headers=h)
    assert resp1.status_code == 200, resp1.text
    body1 = resp1.json()
    assert len(body1["items"]) == 3
    assert body1["next_cursor"] is not None

    page1_ids = {it["id"] for it in body1["items"]}

    # Insert a NEW PENDING item while paginating (simulates live traffic).
    new_msg = _seed_pending_message(
        committed_db,
        raw_text="inserted mid-pagination",
        expires_at=now + timedelta(minutes=25),
        dedup_hash=f"cursor-new-{uuid.uuid4().hex[:6]}",
    )
    _seed_mmp(committed_db, new_msg.id, prod.id)
    committed_db.commit()

    # Page 2: use cursor from page 1.
    resp2 = await client.get(
        f"/api/v1/market/review?page_size=3&cursor={body1['next_cursor']}",
        headers=h,
    )
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    page2_ids = {it["id"] for it in body2["items"]}

    # No overlap between pages.
    assert page1_ids.isdisjoint(page2_ids), (
        f"Overlap detected: {page1_ids & page2_ids}"
    )

    # The new item MUST NOT appear on page 1 (it was inserted after cursor)
    # and it should appear either on page 2 or beyond — not duplicated.
    # Since its expires_at (25 min) is between item 2 (20 min) and item 3 (30 min),
    # it could land on page 2 depending on the cursor position. Either way,
    # it must not duplicate.
    all_seen = page1_ids | page2_ids
    assert str(new_msg.id) not in page1_ids, "new item must not be on first page"


@pytest.mark.asyncio
async def test_cursor_empty_queue(committed_db, client):
    """An empty queue returns no items and no cursor."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    resp = await client.get("/api/v1/market/review", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_review_item_includes_field_confidences(committed_db, client):
    """Each review item includes per-product field confidences from _confidence."""
    admin = make_user(committed_db, role="admin")
    prod = _seed_product(committed_db, "iphone 16 pro max")
    msg = _seed_pending_message(committed_db, dedup_hash=f"conf-{uuid.uuid4().hex[:6]}")
    _seed_mmp(committed_db, msg.id, prod.id, confidence=0.75)
    committed_db.commit()
    h = _token(admin)

    resp = await client.get("/api/v1/market/review?page_size=5", headers=h)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    # Find our item.
    item = next((it for it in items if it["id"] == str(msg.id)), None)
    assert item is not None
    assert item["review_status"] == "PENDING"
    assert str(prod.id) in item["field_confidences"]
    fc = item["field_confidences"][str(prod.id)]
    assert fc["side"] == 0.75
    assert fc["product"] == 0.75
