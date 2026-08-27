"""Integration tests for POST /market/archive/batch — P3 archive relocation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.core.security import create_access_token
from tests.factories import make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


def _archive_item(
    source_msg_id: str,
    *,
    sender_number: str = "+971581234567",
    message_content: str = "WTS iPhone 16 Pro Max 256GB",
    status: str = "lead",
    group_name: str = "Dubai Phones Marketplace",
    sender_name: str = "Ahmed Trader",
    msg_type: str = "seller",
    tags: list | None = None,
) -> dict:
    return {
        "group_name": group_name,
        "sender_name": sender_name,
        "sender_number": sender_number,
        "message_timestamp": datetime.now(UTC).isoformat(),
        "message_content": message_content,
        "msg_type": msg_type,
        "tags": tags or [],
        "source_msg_id": source_msg_id,
        "status": status,
    }


def _archive_batch(*items: dict) -> dict:
    return {"items": list(items)}


# ---------------------------------------------------------------------- idempotency


@pytest.mark.asyncio
async def test_archive_batch_idempotency_replay_same_payload(committed_db, client):
    """Replaying the same batch produces duplicates = N on the second call."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _archive_batch(
        _archive_item("wa-msg-archive-idem-001"),
        _archive_item("wa-msg-archive-idem-002"),
    )

    # First call — inserts both.
    resp = await client.post("/api/v1/market/archive/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["received"] == 2
    assert body["inserted"] == 2
    assert body["duplicates"] == 0

    # Second call — all duplicates (same source_msg_id).
    resp = await client.post("/api/v1/market/archive/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["received"] == 2
    assert body["inserted"] == 0
    assert body["duplicates"] == 2

    # Row count unchanged.
    count = committed_db.execute(
        text("SELECT count(*) FROM market_archive")
    ).scalar_one()
    assert count == 2


# ---------------------------------------------------------------------- noise status


@pytest.mark.asyncio
async def test_archive_noise_rows_carry_noise_status(committed_db, client):
    """Noise-gated messages are stored with status='noise' (Decision #4)."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _archive_batch(
        _archive_item("wa-msg-noise-001", status="noise", message_content="ok"),
    )

    resp = await client.post("/api/v1/market/archive/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["inserted"] == 1

    row = committed_db.execute(
        text("SELECT status, message_content FROM market_archive WHERE source_msg_id = 'wa-msg-noise-001'")
    ).fetchone()
    assert row.status == "noise"


# --------------------------------------------------- source_msg_id uniqueness


@pytest.mark.asyncio
async def test_archive_source_msg_id_uniqueness_enforced(committed_db, client):
    """A duplicate source_msg_id is rejected by the ON CONFLICT clause."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _archive_batch(
        _archive_item("wa-msg-unique-001"),
    )

    resp = await client.post("/api/v1/market/archive/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["inserted"] == 1

    # Replay the same source_msg_id.
    resp = await client.post("/api/v1/market/archive/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["inserted"] == 0
    assert body["duplicates"] == 1

    # Only one row exists.
    count = committed_db.execute(
        text("SELECT count(*) FROM market_archive WHERE source_msg_id = 'wa-msg-unique-001'")
    ).scalar_one()
    assert count == 1


# -------------------------------------------------------- invalid status rejected


@pytest.mark.asyncio
async def test_archive_invalid_status_rejected(committed_db, client):
    """The Pydantic pattern validator rejects status values outside {lead, noise, unreviewed}."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _archive_batch(
        _archive_item("wa-msg-bad-status", status="garbage"),
    )

    resp = await client.post("/api/v1/market/archive/batch", json=payload, headers=h)
    assert resp.status_code == 422  # Pydantic validation error


# ---------------------------------------------------------- mixed batch


@pytest.mark.asyncio
async def test_archive_mixed_lead_and_noise_in_one_batch(committed_db, client):
    """A single batch can contain both lead and noise records."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _archive_batch(
        _archive_item("wa-msg-mixed-lead", status="lead", message_content="WTS iPhone"),
        _archive_item("wa-msg-mixed-noise", status="noise", message_content="ok thanks"),
    )

    resp = await client.post("/api/v1/market/archive/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["received"] == 2
    assert body["inserted"] == 2

    lead_row = committed_db.execute(
        text("SELECT status FROM market_archive WHERE source_msg_id = 'wa-msg-mixed-lead'")
    ).fetchone()
    assert lead_row.status == "lead"

    noise_row = committed_db.execute(
        text("SELECT status FROM market_archive WHERE source_msg_id = 'wa-msg-mixed-noise'")
    ).fetchone()
    assert noise_row.status == "noise"


# ------------------------------------------------------------- tags stored


@pytest.mark.asyncio
async def test_archive_tags_stored_as_jsonb(committed_db, client):
    """Tags are stored as a JSONB array and retrievable."""
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    h = _token(admin)

    payload = _archive_batch(
        _archive_item(
            "wa-msg-tags-001",
            tags=["Apple", "iPhone", "256GB", "Dubai"],
        ),
    )

    resp = await client.post("/api/v1/market/archive/batch", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    assert resp.json()["inserted"] == 1

    row = committed_db.execute(
        text("SELECT tags FROM market_archive WHERE source_msg_id = 'wa-msg-tags-001'")
    ).fetchone()
    assert "Apple" in row.tags
    assert "Dubai" in row.tags
