"""Integration tests for Phase 7 — Attribute Vocabulary API."""

from __future__ import annotations

import uuid

import pytest

from app.core.security import create_access_token
from app.modules.market.models import AttributeVocab
from tests.factories import make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


def _seed_entry(session, **kwargs) -> AttributeVocab:
    """Seed a single vocab entry with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "category": "region",
        "kind": "closed",
        "tag": f"TEST_{uuid.uuid4().hex[:8]}",
        "canonical": "Test Entry",
        "aliases": [],
        "is_active": True,
    }
    defaults.update(kwargs)
    entry = AttributeVocab(**defaults)
    session.add(entry)
    session.flush()
    return entry


# ---------------------------------------------------------------------------
# Seed endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_creates_all_categories(committed_db, client):
    """Seed endpoint creates entries across all expected categories."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()

    resp = await client.post(
        "/api/v1/market/vocab/seed", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["upserted"] > 0

    # Verify expected categories exist.
    resp2 = await client.get(
        "/api/v1/market/vocab?active_only=true", headers=_token(admin)
    )
    assert resp2.status_code == 200, resp2.text
    items = resp2.json()
    categories = {i["category"] for i in items}

    expected_closed = {
        "region", "activation", "condition", "logistics",
        "currency", "variant", "risk", "trust", "side",
    }
    expected_open = {"color", "brand"}

    assert expected_closed <= categories, f"Missing closed: {expected_closed - categories}"
    assert expected_open <= categories, f"Missing open: {expected_open - categories}"


@pytest.mark.asyncio
async def test_seed_is_idempotent(committed_db, client):
    """Running seed twice produces the same state — no duplicates."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()

    resp1 = await client.post(
        "/api/v1/market/vocab/seed", headers=_token(admin)
    )
    assert resp1.status_code == 200, resp1.text
    count1 = resp1.json()["upserted"]

    resp2 = await client.post(
        "/api/v1/market/vocab/seed", headers=_token(admin)
    )
    assert resp2.status_code == 200, resp2.text
    count2 = resp2.json()["upserted"]

    # Second seed should upsert the same number of entries (no new ones).
    assert count2 == count1

    # Verify no duplicate (category, tag) pairs.
    resp3 = await client.get(
        "/api/v1/market/vocab?active_only=true", headers=_token(admin)
    )
    items = resp3.json()
    pairs = [(i["category"], i["tag"]) for i in items]
    assert len(pairs) == len(set(pairs)), "Duplicate pairs found"


@pytest.mark.asyncio
async def test_seed_admin_only(committed_db, client):
    """Seed endpoint is admin-only."""
    agent = make_user(committed_db, role="agent")
    committed_db.commit()

    resp = await client.post(
        "/api/v1/market/vocab/seed", headers=_token(agent)
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# List / read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vocab_filter_by_category(committed_db, client):
    """GET /vocab?category= filters correctly."""
    admin = make_user(committed_db, role="admin")
    _seed_entry(committed_db, category="region", tag="TAG_A", canonical="A")
    _seed_entry(committed_db, category="region", tag="TAG_B", canonical="B")
    _seed_entry(committed_db, category="color", tag="Red", canonical="Red")
    committed_db.commit()

    resp = await client.get(
        "/api/v1/market/vocab?category=region", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 2
    assert all(i["category"] == "region" for i in items)


@pytest.mark.asyncio
async def test_list_vocab_filter_by_kind(committed_db, client):
    """GET /vocab?kind= filters by open/closed."""
    admin = make_user(committed_db, role="admin")
    _seed_entry(committed_db, category="region", kind="closed", tag="TAG_A", canonical="A")
    _seed_entry(committed_db, category="color", kind="open", tag="Blue", canonical="Blue")
    committed_db.commit()

    resp = await client.get(
        "/api/v1/market/vocab?kind=open", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    assert items[0]["kind"] == "open"


@pytest.mark.asyncio
async def test_list_vocab_active_only(committed_db, client):
    """Inactive entries are hidden when active_only=true (default)."""
    admin = make_user(committed_db, role="admin")
    _seed_entry(committed_db, category="region", tag="ACTIVE", canonical="Active", is_active=True)
    _seed_entry(committed_db, category="region", tag="INACTIVE", canonical="Inactive", is_active=False)
    committed_db.commit()

    resp = await client.get(
        "/api/v1/market/vocab?category=region&active_only=true", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    assert items[0]["tag"] == "ACTIVE"

    # With active_only=false, both appear.
    resp2 = await client.get(
        "/api/v1/market/vocab?category=region&active_only=false", headers=_token(admin)
    )
    assert resp2.status_code == 200, resp2.text
    assert len(resp2.json()) == 2


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_vocab_entry(committed_db, client):
    """POST /vocab creates a new entry."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()

    resp = await client.post(
        "/api/v1/market/vocab",
        json={
            "category": "region",
            "kind": "closed",
            "tag": "REGION_TEST",
            "canonical": "Test Region",
            "aliases": ["test", "tst"],
        },
        headers=_token(admin),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["category"] == "region"
    assert body["kind"] == "closed"
    assert body["tag"] == "REGION_TEST"
    assert body["canonical"] == "Test Region"
    assert body["aliases"] == ["test", "tst"]
    assert body["is_active"] is True
    assert "id" in body


@pytest.mark.asyncio
async def test_create_vocab_invalid_kind(committed_db, client):
    """POST /vocab rejects invalid kind values."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()

    resp = await client.post(
        "/api/v1/market/vocab",
        json={
            "category": "region",
            "kind": "invalid_kind",
            "tag": "TEST",
            "canonical": "Test",
        },
        headers=_token(admin),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_vocab_duplicate_tag(committed_db, client):
    """POST /vocab with duplicate (category, tag) returns 409."""
    admin = make_user(committed_db, role="admin")
    _seed_entry(committed_db, category="region", tag="DUP_TAG", canonical="Existing")
    committed_db.commit()

    resp = await client.post(
        "/api/v1/market/vocab",
        json={
            "category": "region",
            "kind": "closed",
            "tag": "DUP_TAG",
            "canonical": "Duplicate",
        },
        headers=_token(admin),
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_create_vocab_admin_only(committed_db, client):
    """POST /vocab is admin-only."""
    agent = make_user(committed_db, role="agent")
    committed_db.commit()

    resp = await client.post(
        "/api/v1/market/vocab",
        json={
            "category": "region",
            "kind": "closed",
            "tag": "TEST",
            "canonical": "Test",
        },
        headers=_token(agent),
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_vocab_canonical(committed_db, client):
    """PATCH /vocab/{id} updates canonical label."""
    admin = make_user(committed_db, role="admin")
    entry = _seed_entry(committed_db, category="region", tag="UPDATE_ME", canonical="Old Label")
    committed_db.commit()

    resp = await client.patch(
        f"/api/v1/market/vocab/{entry.id}",
        json={"canonical": "New Label"},
        headers=_token(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["canonical"] == "New Label"


@pytest.mark.asyncio
async def test_update_vocab_aliases(committed_db, client):
    """PATCH /vocab/{id} can add aliases."""
    admin = make_user(committed_db, role="admin")
    entry = _seed_entry(committed_db, category="color", kind="open", tag="Crimson", canonical="Crimson")
    committed_db.commit()

    resp = await client.patch(
        f"/api/v1/market/vocab/{entry.id}",
        json={"aliases": ["crimson red", "deep red"]},
        headers=_token(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["aliases"] == ["crimson red", "deep red"]


@pytest.mark.asyncio
async def test_update_vocab_soft_delete(committed_db, client):
    """PATCH /vocab/{id} with is_active=false soft-deletes."""
    admin = make_user(committed_db, role="admin")
    entry = _seed_entry(committed_db, category="region", tag="TO_DEACTIVATE", canonical="Deactivate")
    committed_db.commit()

    resp = await client.patch(
        f"/api/v1/market/vocab/{entry.id}",
        json={"is_active": False},
        headers=_token(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False

    # Should not appear in default (active_only=true) listing.
    resp2 = await client.get(
        "/api/v1/market/vocab?category=region", headers=_token(admin)
    )
    tags = [i["tag"] for i in resp2.json()]
    assert "TO_DEACTIVATE" not in tags


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_vocab_entry(committed_db, client):
    """DELETE /vocab/{id} hard-deletes the entry."""
    admin = make_user(committed_db, role="admin")
    entry = _seed_entry(committed_db, category="region", tag="DELETE_ME", canonical="Delete Me")
    committed_db.commit()

    resp = await client.delete(
        f"/api/v1/market/vocab/{entry.id}", headers=_token(admin)
    )
    assert resp.status_code == 204, resp.text

    # Verify it's gone.
    resp2 = await client.get(
        "/api/v1/market/vocab?category=region", headers=_token(admin)
    )
    tags = [i["tag"] for i in resp2.json()]
    assert "DELETE_ME" not in tags


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_404(committed_db, client):
    """DELETE /vocab/{id} for nonexistent ID returns 404."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()

    resp = await client.delete(
        f"/api/v1/market/vocab/{uuid.uuid4()}", headers=_token(admin)
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Agent access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_can_read_vocab(committed_db, client):
    """Agents can read vocab (GET /vocab)."""
    agent = make_user(committed_db, role="agent")
    _seed_entry(committed_db, category="region", tag="VISIBLE", canonical="Visible")
    committed_db.commit()

    resp = await client.get(
        "/api/v1/market/vocab?category=region", headers=_token(agent)
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
