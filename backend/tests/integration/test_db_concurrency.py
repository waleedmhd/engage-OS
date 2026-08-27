"""Integration-tier concurrency tests against a real PostgreSQL database.

These tests cover bugs that an in-memory SQLite engine cannot reproduce:

- DB-I7: ContactRepository.upsert_by_phone_sync race recovery via SAVEPOINT
- DB-I8: MessageRepository.increment_retry_sync atomicity under concurrent
        Celery workers

Skipped automatically when DATABASE_URL_SYNC is not configured. Run with:
    DATABASE_URL_SYNC=postgresql+psycopg://... pytest -m integration
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Skip the entire module when no real DB is configured.
_DB_URL = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL")
if not _DB_URL or not _DB_URL.startswith(("postgresql://", "postgresql+psycopg://")):
    pytest.skip(
        "Integration concurrency tests require DATABASE_URL_SYNC pointing at "
        "a real PostgreSQL instance.",
        allow_module_level=True,
    )

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine(_DB_URL, future=True, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def sync_factory(sync_engine):
    return sessionmaker(sync_engine, autoflush=False, autocommit=False, expire_on_commit=False)


# ----------------------------------------------------------------- DB-I7

def test_upsert_by_phone_concurrent_race_savepoint_recovery(sync_factory):
    """DB-I7: Two threads racing to upsert the same phone must NOT poison
    the outer transaction. Both should end up returning a Contact for the
    same phone (one wins the INSERT, the other catches IntegrityError
    inside a SAVEPOINT and reads the existing row)."""
    from app.modules.contacts.repository import ContactRepository

    phone = f"+1555{uuid.uuid4().int % 10**7:07d}"
    barrier = threading.Barrier(2)
    results: list[object] = [None, None]
    errors: list[Exception | None] = [None, None]

    def worker(idx: int) -> None:
        try:
            with sync_factory() as session:
                repo = ContactRepository(session)
                barrier.wait(timeout=5)  # release both threads simultaneously
                results[idx] = repo.upsert_by_phone_sync(phone=phone, name=f"w{idx}")
                session.commit()
        except Exception as exc:
            errors[idx] = exc

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    # Cleanup
    with sync_factory() as session:
        session.execute(
            sa.text("DELETE FROM contacts WHERE phone = :phone"), {"phone": phone}
        )
        session.commit()

    assert errors[0] is None, f"worker 0 raised: {errors[0]!r}"
    assert errors[1] is None, f"worker 1 raised: {errors[1]!r}"
    assert results[0] is not None and results[1] is not None
    # Both observers see the same contact ID.
    assert results[0].id == results[1].id


# ----------------------------------------------------------------- DB-I8

def test_increment_retry_atomic_under_concurrent_workers(sync_factory):
    """DB-I8: 10 concurrent increment_retry_sync calls must result in
    retry_count == 10. The buggy read-modify-write pattern would lose
    increments under concurrency."""
    from app.modules.contacts.repository import ContactRepository
    from app.modules.conversations.repository import ConversationRepository
    from app.modules.messaging.constants import (
        MessageDeliveryStatus,
        MessageDirection,
        SenderType,
    )
    from app.modules.messaging.repository import MessageRepository

    # Setup a contact + conversation + queued message to attack.
    phone = f"+1555{uuid.uuid4().int % 10**7:07d}"
    with sync_factory() as session:
        contact = ContactRepository(session).upsert_by_phone_sync(phone=phone)
        conv = ConversationRepository(session).create_for_contact_sync(
            contact_id=contact.id
        )
        msg = MessageRepository(session).create_sync(
            conversation_id=conv.id,
            direction=MessageDirection.OUTBOUND,
            sender_type=SenderType.AGENT,
            content="x",
            delivery_status=MessageDeliveryStatus.QUEUED,
            retry_count=0,
        )
        session.commit()
        msg_id = msg.id
        cleanup_ids = (msg_id, conv.id, contact.id)

    n_workers = 10

    def worker() -> None:
        with sync_factory() as session:
            MessageRepository(session).increment_retry_sync(msg_id)
            session.commit()

    threads = [threading.Thread(target=worker) for _ in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # Read final count.
    with sync_factory() as session:
        final = session.execute(
            sa.text("SELECT retry_count FROM messages WHERE id = :id"),
            {"id": cleanup_ids[0]},
        ).scalar_one()

    # Cleanup
    with sync_factory() as session:
        session.execute(
            sa.text("DELETE FROM messages WHERE id = :id"), {"id": cleanup_ids[0]}
        )
        session.execute(
            sa.text("DELETE FROM conversations WHERE id = :id"), {"id": cleanup_ids[1]}
        )
        session.execute(
            sa.text("DELETE FROM contacts WHERE id = :id"), {"id": cleanup_ids[2]}
        )
        session.commit()

    assert final == n_workers, (
        f"DB-I8 regression: expected retry_count={n_workers}, got {final}. "
        "Read-modify-write race lost an increment."
    )
