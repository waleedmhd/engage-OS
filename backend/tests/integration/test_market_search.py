"""Integration tests for Phase 11 — Search Hardening.

Tests FTS tokenization, cursor pagination stability, and edge cases.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.security import create_access_token
from app.modules.market.models import MarketMessage, Product, ProductAlias
from tests.factories import make_user


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
    raw_text: str,
    side: str = "SELL",
    captured_at: datetime | None = None,
    dedup_hash: str | None = None,
) -> MarketMessage:
    now = datetime.now(tz=UTC)
    msg = MarketMessage(
        id=uuid.uuid4(),
        source_type="group",
        source_id="chat-test",
        sender_raw="+971501234567",
        side=side,
        raw_text=raw_text,
        normalized_text=raw_text.lower(),
        captured_at=captured_at or now,
        expires_at=now + timedelta(hours=48),
        status="ACTIVE",
        review_status="AUTO",
        dedup_hash=dedup_hash or f"search-test-{uuid.uuid4().hex[:12]}",
    )
    session.add(msg)
    session.flush()
    return msg


# ---------------------------------------------------------------------- FTS tokenization


@pytest.mark.asyncio
async def test_fts_tokenization_matches_case_and_punctuation(committed_db, client):
    """Search "iphone 16" matches "iPhone 16 Pro Max" (tokenization works)."""
    admin = make_user(committed_db, role="admin")
    _seed_message(committed_db, raw_text="WTS iPhone 16 Pro Max 256GB sealed")
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=iphone+16&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    assert len(combined) >= 1
    texts = [item["raw_text"] for item in combined]
    assert any("iPhone 16 Pro Max" in t for t in texts)


@pytest.mark.asyncio
async def test_fts_exclusion_search(committed_db, client):
    """Search "iphone -samsung" excludes Samsung results."""
    admin = make_user(committed_db, role="admin")
    _seed_message(committed_db, raw_text="WTS iPhone 16 Pro Max", dedup_hash="excl-1")
    _seed_message(committed_db, raw_text="WTS Samsung S25 Ultra", dedup_hash="excl-2")
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=iphone+-samsung&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    texts = [item["raw_text"] for item in combined]
    assert any("iPhone" in t for t in texts)
    assert not any("Samsung" in t for t in texts)


@pytest.mark.asyncio
async def test_fts_multi_token_match(committed_db, client):
    """Search "256GB sealed" matches messages with both tokens."""
    admin = make_user(committed_db, role="admin")
    _seed_message(committed_db, raw_text="WTS iPhone 16 Pro Max 256GB sealed", dedup_hash="multi-1")
    _seed_message(committed_db, raw_text="WTS iPhone 14 128GB used", dedup_hash="multi-2")
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=256GB+sealed&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    texts = [item["raw_text"] for item in combined]
    assert any("256GB sealed" in t for t in texts)
    assert not any("128GB used" in t for t in texts)


# ---------------------------------------------------------------------- cursor pagination


@pytest.mark.asyncio
async def test_cursor_pagination_no_dupes_no_gaps(committed_db, client):
    """Page 1 → page 2 → page 3 returns no dupes and no gaps."""
    admin = make_user(committed_db, role="admin")
    base = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
    for i in range(5):
        _seed_message(
            committed_db,
            raw_text=f"WTS test item number {i}",
            captured_at=base + timedelta(minutes=i),
            dedup_hash=f"cursor-{i}",
        )
    committed_db.commit()
    h = _token(admin)

    seen: set[str] = set()
    cursor: str | None = None
    pages = 0
    while True:
        params = f"q=test+item&page_size=2"
        if cursor:
            params += f"&cursor={cursor}"
        resp = await client.get(f"/api/v1/market/search?{params}", headers=h)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        combined = data["buy_items"] + data["sell_items"]
        for item in combined:
            mid = item["market_message_id"]
            assert mid not in seen, f"Duplicate message {mid} on page {pages + 1}"
            seen.add(mid)
        pages += 1
        cursor = data.get("next_cursor")
        if not data.get("has_more"):
            break

    assert pages >= 3, f"Expected at least 3 pages, got {pages}"
    assert len(seen) == 5, f"Expected 5 unique messages, got {len(seen)}"


@pytest.mark.asyncio
async def test_keyset_stable_under_concurrent_insert(committed_db, client):
    """Inserting a new message while paginating doesn't shift results."""
    admin = make_user(committed_db, role="admin")
    base = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
    # Seed 4 messages, oldest-to-newest.
    for i in range(4):
        _seed_message(
            committed_db,
            raw_text=f"WTS stable test item {i}",
            captured_at=base + timedelta(minutes=i),
            dedup_hash=f"stable-{i}",
        )
    committed_db.commit()
    h = _token(admin)

    # Fetch page 1 (2 items).
    resp1 = await client.get(
        "/api/v1/market/search?q=stable+test&page_size=2", headers=h
    )
    assert resp1.status_code == 200, resp1.text
    page1 = resp1.json()
    page1_ids = {item["market_message_id"] for item in page1["buy_items"] + page1["sell_items"]}
    assert len(page1_ids) == 2
    cursor = page1["next_cursor"]
    assert cursor is not None

    # Insert a new message between pages (newer than all existing).
    _seed_message(
        committed_db,
        raw_text="WTS stable test item NEW",
        captured_at=base + timedelta(minutes=10),
        dedup_hash="stable-new",
    )
    committed_db.commit()

    # Fetch page 2 — should not contain any page-1 items.
    resp2 = await client.get(
        f"/api/v1/market/search?q=stable+test&page_size=2&cursor={cursor}", headers=h
    )
    assert resp2.status_code == 200, resp2.text
    page2 = resp2.json()
    page2_ids = {item["market_message_id"] for item in page2["buy_items"] + page2["sell_items"]}

    # No dupes between pages.
    assert page1_ids.isdisjoint(page2_ids), f"Overlap: {page1_ids & page2_ids}"


@pytest.mark.asyncio
async def test_empty_query_returns_all_sorted(committed_db, client):
    """Empty query returns all messages sorted by captured_at DESC."""
    admin = make_user(committed_db, role="admin")
    base = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
    for i in range(3):
        _seed_message(
            committed_db,
            raw_text=f"WTS empty query test {i}",
            captured_at=base + timedelta(minutes=i),
            dedup_hash=f"empty-{i}",
        )
    committed_db.commit()
    h = _token(admin)

    resp = await client.get("/api/v1/market/search?page_size=50", headers=h)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    assert len(combined) == 3
    # Verify DESC order: most recent first.
    timestamps = [item["captured_at"] for item in combined]
    assert timestamps == sorted(timestamps, reverse=True), f"Not DESC: {timestamps}"


@pytest.mark.asyncio
async def test_fts_special_characters_no_crash(committed_db, client):
    """Search with special FTS characters doesn't crash."""
    admin = make_user(committed_db, role="admin")
    _seed_message(committed_db, raw_text="WTS iPhone & Samsung | Google !!! test")
    committed_db.commit()
    h = _token(admin)

    # These queries may return 0 results but must not 500.
    for chars in ["&", "|", "!", "!!!", "iphone & samsung"]:
        resp = await client.get(
            f"/api/v1/market/search?q={chars}&page_size=50", headers=h
        )
        assert resp.status_code == 200, f"Failed for query '{chars}': {resp.text}"


@pytest.mark.asyncio
async def test_cursor_pagination_prev_and_next(committed_db, client):
    """Prev/next cursor navigation works correctly."""
    admin = make_user(committed_db, role="admin")
    base = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
    for i in range(6):
        _seed_message(
            committed_db,
            raw_text=f"WTS pagination nav test {i}",
            captured_at=base + timedelta(minutes=i),
            dedup_hash=f"nav-{i}",
        )
    committed_db.commit()
    h = _token(admin)

    # Page 1.
    resp = await client.get(
        "/api/v1/market/search?q=pagination+nav&page_size=2", headers=h
    )
    assert resp.status_code == 200
    p1 = resp.json()
    p1_ids = {item["market_message_id"] for item in p1["buy_items"] + p1["sell_items"]}
    assert len(p1_ids) == 2
    assert p1["has_more"] is True
    c1 = p1["next_cursor"]

    # Page 2.
    resp = await client.get(
        f"/api/v1/market/search?q=pagination+nav&page_size=2&cursor={c1}", headers=h
    )
    assert resp.status_code == 200
    p2 = resp.json()
    p2_ids = {item["market_message_id"] for item in p2["buy_items"] + p2["sell_items"]}
    assert len(p2_ids) == 2
    assert p1_ids.isdisjoint(p2_ids)
    assert p2["has_more"] is True
    c2 = p2["next_cursor"]

    # Page 3.
    resp = await client.get(
        f"/api/v1/market/search?q=pagination+nav&page_size=2&cursor={c2}", headers=h
    )
    assert resp.status_code == 200
    p3 = resp.json()
    p3_ids = {item["market_message_id"] for item in p3["buy_items"] + p3["sell_items"]}
    assert len(p3_ids) == 2
    assert p1_ids.isdisjoint(p3_ids) and p2_ids.isdisjoint(p3_ids)
    assert p3["has_more"] is False
    assert p3["next_cursor"] is None


@pytest.mark.asyncio
async def test_invalid_cursor_handled_gracefully(committed_db, client):
    """An invalid/truncated cursor is treated as null (no crash, first page)."""
    admin = make_user(committed_db, role="admin")
    _seed_message(committed_db, raw_text="WTS graceful cursor test")
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=graceful+cursor&cursor=not-valid-base64!!", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    assert len(combined) >= 1  # Falls back to page 1.


# ---------------------------------------------------------------------- vocab expansion


def _seed_vocab_entry(session, **kwargs) -> None:
    """Seed a single attribute_vocab entry."""
    from app.modules.market.models import AttributeVocab

    defaults = {
        "id": uuid.uuid4(),
        "category": "color",
        "kind": "open",
        "tag": f"TEST_{uuid.uuid4().hex[:8]}",
        "canonical": "Test",
        "aliases": [],
        "is_active": True,
    }
    defaults.update(kwargs)
    session.add(AttributeVocab(**defaults))
    session.flush()


@pytest.mark.asyncio
async def test_vocab_expansion_color_alias(committed_db, client):
    """Search "black" finds messages with the alias "blk" (color vocab expansion)."""
    admin = make_user(committed_db, role="admin")
    _seed_vocab_entry(
        committed_db,
        category="color",
        kind="open",
        tag="Black",
        canonical="Black",
        aliases=["black", "blk", "bank"],
    )
    _seed_message(
        committed_db,
        raw_text="WTS iPhone 16 Pro Max blk 256GB",
        dedup_hash="vocab-color-1",
    )
    _seed_message(
        committed_db,
        raw_text="WTS Samsung S25 not-matching-color",
        dedup_hash="vocab-color-2",
    )
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=black&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    texts = [item["raw_text"] for item in combined]
    assert any("blk" in t for t in texts), f"Expected to find 'blk' message via vocab expansion, got: {texts}"
    assert not any("not-matching" in t for t in texts)


@pytest.mark.asyncio
async def test_vocab_expansion_region_alias(committed_db, client):
    """Search "UK" finds messages with "UK ONLY" or "UK Spec" (region vocab expansion)."""
    admin = make_user(committed_db, role="admin")
    _seed_vocab_entry(
        committed_db,
        category="region",
        kind="closed",
        tag="REGION_UK",
        canonical="UK spec",
        aliases=["UK", "UK Spec", "UK ONLY", "/B"],
    )
    _seed_message(
        committed_db,
        raw_text="WTS iPhone 16 UK ONLY stock available",
        dedup_hash="vocab-region-1",
    )
    _seed_message(
        committed_db,
        raw_text="WTS Samsung S25 JP spec",
        dedup_hash="vocab-region-2",
    )
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=UK&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    texts = [item["raw_text"] for item in combined]
    assert any("UK ONLY" in t for t in texts), f"Expected to find 'UK ONLY' message, got: {texts}"


@pytest.mark.asyncio
async def test_vocab_expansion_condition_alias(committed_db, client):
    """Search "Brand New" finds messages with related condition aliases."""
    admin = make_user(committed_db, role="admin")
    _seed_vocab_entry(
        committed_db,
        category="condition",
        kind="closed",
        tag="COND_NEW",
        canonical="New",
        aliases=["Brand New", "New stock", "OEM Brand New", "Original Brand New"],
    )
    _seed_message(
        committed_db,
        raw_text="WTS iPhone 16 OEM Brand New sealed",
        dedup_hash="vocab-cond-1",
    )
    _seed_message(
        committed_db,
        raw_text="WTS Samsung S25 used grade B",
        dedup_hash="vocab-cond-2",
    )
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=Brand+New&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    texts = [item["raw_text"] for item in combined]
    assert any("OEM Brand New" in t for t in texts), f"Expected to find 'OEM Brand New' message, got: {texts}"


@pytest.mark.asyncio
async def test_vocab_expansion_no_match_unaffected(committed_db, client):
    """Search with no vocab match works as before (no false positives)."""
    admin = make_user(committed_db, role="admin")
    _seed_vocab_entry(
        committed_db,
        category="color",
        kind="open",
        tag="Black",
        canonical="Black",
        aliases=["black", "blk"],
    )
    _seed_message(
        committed_db,
        raw_text="WTS iPhone 16 Pro Max 256GB",
        dedup_hash="vocab-nomatch-1",
    )
    _seed_message(
        committed_db,
        raw_text="WTS blk Samsung S25",
        dedup_hash="vocab-nomatch-2",
    )
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=iPhone+256GB&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    texts = [item["raw_text"] for item in combined]
    # Should find iPhone message but NOT the blk Samsung (which doesn't match "iPhone 256GB")
    assert any("iPhone 16 Pro Max" in t for t in texts)
    assert not any("Samsung" in t for t in texts)


@pytest.mark.asyncio
async def test_vocab_expansion_inactive_entry_ignored(committed_db, client):
    """Inactive vocab entries are not used for query expansion."""
    admin = make_user(committed_db, role="admin")
    _seed_vocab_entry(
        committed_db,
        category="color",
        kind="open",
        tag="Black",
        canonical="Black",
        aliases=["black", "blk"],
        is_active=False,
    )
    _seed_message(
        committed_db,
        raw_text="WTS iPhone 16 blk 256GB",
        dedup_hash="vocab-inactive-1",
    )
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=black&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    # Without vocab expansion, FTS won't match "blk" for "black" (different tokens)
    texts = [item["raw_text"] for item in combined]
    assert not any("blk" in t for t in texts), (
        f"Should NOT find 'blk' message — vocab entry is inactive, got: {texts}"
    )


@pytest.mark.asyncio
async def test_vocab_expansion_short_query_matches_long_term(committed_db, client):
    """A short query that is a substring of a longer vocab term triggers expansion.

    Searching "iphone" should match entries whose canonical or aliases contain
    "iphone" (e.g. "iPhone 17 Pro Max") and expand to related model terms.
    """
    admin = make_user(committed_db, role="admin")
    _seed_vocab_entry(
        committed_db,
        category="brand",
        kind="open",
        tag="iphone 17 pro max",
        canonical="iPhone 17 Pro Max",
        aliases=["17 pro max", "17 pro", "iphone 17"],
    )
    _seed_message(
        committed_db,
        raw_text="WTS 17 pro max 256GB sealed",
        dedup_hash="vocab-short-1",
    )
    _seed_message(
        committed_db,
        raw_text="WTS Samsung S25 ultra 512GB",
        dedup_hash="vocab-short-2",
    )
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=iphone&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    texts = [item["raw_text"] for item in combined]
    assert any("17 pro max" in t for t in texts), (
        f"Expected 'iphone' search to find '17 pro max' message via bidirectional vocab expansion, got: {texts}"
    )
    assert not any("Samsung" in t for t in texts)


@pytest.mark.asyncio
async def test_vocab_expansion_brand_to_alias(committed_db, client):
    """Searching a brand name ("apple") expands to product aliases and finds messages containing them."""
    admin = make_user(committed_db, role="admin")
    _seed_vocab_entry(
        committed_db,
        category="brand",
        kind="open",
        tag="apple",
        canonical="Apple",
        aliases=["iphone", "ipad", "macbook"],
    )
    _seed_message(
        committed_db,
        raw_text="WTS iphone 16 pro max 256GB sealed",
        dedup_hash="vocab-brand-1",
    )
    _seed_message(
        committed_db,
        raw_text="WTS Samsung A56 blue",
        dedup_hash="vocab-brand-2",
    )
    committed_db.commit()
    h = _token(admin)

    resp = await client.get(
        "/api/v1/market/search?q=apple&page_size=50", headers=h
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    combined = data["buy_items"] + data["sell_items"]
    texts = [item["raw_text"] for item in combined]
    assert any("iphone" in t for t in texts), (
        f"Expected 'apple' search to expand to 'iphone' and find matching message, got: {texts}"
    )
    assert not any("Samsung" in t for t in texts)
