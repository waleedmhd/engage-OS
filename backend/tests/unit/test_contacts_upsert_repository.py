"""Unit tests for ContactRepository.upsert_by_phone_append.

Uses `async_pg_session` and `pg_session` (function-scoped, SAVEPOINT-rolled-back).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.contacts.models import Contact
from app.modules.contacts.repository import ContactRepository


# ----------------------------------------------------------- async variant

@pytest.mark.asyncio
async def test_upsert_append_creates_new_contact(async_pg_session):
    repo = ContactRepository(async_pg_session)
    contact = await repo.upsert_by_phone_append(
        phone="15551119991",
        name="Ahmed Trader",
        information="Intent: WTB | Brand: Apple",
    )
    await async_pg_session.flush()

    assert contact.phone == "15551119991"
    assert contact.name == "Ahmed Trader"
    assert contact.information == "Intent: WTB | Brand: Apple"

    row = await async_pg_session.execute(
        select(Contact).where(Contact.phone == "15551119991")
    )
    assert row.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_upsert_append_appends_to_existing(async_pg_session):
    repo = ContactRepository(async_pg_session)

    await repo.upsert_by_phone_append(
        phone="15551119992",
        name="Sara Seller",
        information="Intent: WTS | Brand: Samsung",
    )
    await async_pg_session.flush()

    contact = await repo.upsert_by_phone_append(
        phone="15551119992",
        information="Intent: WTB | Brand: Apple | Storage: 256GB",
    )
    await async_pg_session.flush()

    assert "WTS | Brand: Samsung" in contact.information
    assert "WTB | Brand: Apple" in contact.information
    assert "\n\n---\n\n" in contact.information


@pytest.mark.asyncio
async def test_upsert_append_preserves_existing_name(async_pg_session):
    repo = ContactRepository(async_pg_session)

    await repo.upsert_by_phone_append(
        phone="15551119993",
        name="Ahmed Al-Rashid Trading LLC",
        information="Intent: WTB | Brand: Apple",
    )
    await async_pg_session.flush()

    contact = await repo.upsert_by_phone_append(
        phone="15551119993",
        name="Ahmed",
        information="Intent: WTB | Brand: Samsung",
    )
    await async_pg_session.flush()

    assert contact.name == "Ahmed Al-Rashid Trading LLC"
    assert "WTB | Brand: Samsung" in contact.information


@pytest.mark.asyncio
async def test_upsert_append_second_call_is_idempotent(async_pg_session):
    repo = ContactRepository(async_pg_session)

    c1 = await repo.upsert_by_phone_append(
        phone="15551119994",
        name="First",
        information="First info",
    )
    await async_pg_session.flush()

    c2 = await repo.upsert_by_phone_append(
        phone="15551119994",
        name="Second",
        information="Second info",
    )
    await async_pg_session.flush()

    assert c1.id == c2.id
    assert "First info" in c2.information
    assert "Second info" in c2.information


@pytest.mark.asyncio
async def test_upsert_by_phone_seeds_empty_information(async_pg_session):
    """upsert_by_phone sets information when existing row has none."""
    # Create without information first
    c1 = await ContactRepository(async_pg_session).upsert_by_phone(
        phone="15551119995",
    )
    await async_pg_session.flush()
    assert c1.information is None

    # Now call with information — guard passes (existing.information is None)
    c2 = await ContactRepository(async_pg_session).upsert_by_phone(
        phone="15551119995",
        information="Fresh info",
    )
    await async_pg_session.flush()

    assert c2.information == "Fresh info"


@pytest.mark.asyncio
async def test_upsert_by_phone_guards_existing_information(async_pg_session):
    """upsert_by_phone does NOT overwrite already-set information."""
    repo = ContactRepository(async_pg_session)

    c1 = await repo.upsert_by_phone(
        phone="15551119996",
        information="Initial info",
    )
    await async_pg_session.flush()
    assert c1.information == "Initial info"

    c2 = await repo.upsert_by_phone(
        phone="15551119996",
        information="Should be ignored",
    )
    await async_pg_session.flush()

    assert c1.id == c2.id
    assert c2.information == "Initial info"


# ----------------------------------------------------------- sync variant


def test_upsert_append_sync_creates(pg_session):
    """Sync variant: fresh phone creates the row."""
    repo = ContactRepository(pg_session)
    contact = repo.upsert_by_phone_append_sync(
        phone="15551119995",
        name="Sync Trader",
        information="Sync-created info",
    )
    pg_session.flush()

    assert contact.phone == "15551119995"
    assert contact.name == "Sync Trader"
    assert contact.information == "Sync-created info"

    row = pg_session.execute(
        select(Contact).where(Contact.phone == "15551119995")
    )
    assert row.scalar_one_or_none() is not None


def test_upsert_append_sync_appends(pg_session):
    """Sync variant: second call for same phone appends with separator."""
    repo = ContactRepository(pg_session)

    repo.upsert_by_phone_append_sync(
        phone="15551119996",
        name="Sync Sara",
        information="Sync WTS | Brand: Samsung",
    )
    pg_session.flush()

    contact = repo.upsert_by_phone_append_sync(
        phone="15551119996",
        information="Sync WTB | Brand: Apple",
    )
    pg_session.flush()

    assert "WTS | Brand: Samsung" in contact.information
    assert "WTB | Brand: Apple" in contact.information
    assert "\n\n---\n\n" in contact.information


def test_upsert_append_sync_preserves_name(pg_session):
    """Sync variant: name only set on creation, not on subsequent calls."""
    repo = ContactRepository(pg_session)

    repo.upsert_by_phone_append_sync(
        phone="15551119997",
        name="Sync Company LLC",
        information="First info",
    )
    pg_session.flush()

    contact = repo.upsert_by_phone_append_sync(
        phone="15551119997",
        name="Sync",
        information="Second info",
    )
    pg_session.flush()

    assert contact.name == "Sync Company LLC"
    assert "Second info" in contact.information


def test_upsert_append_sync_idempotent(pg_session):
    """Sync variant: repeated calls return same row."""
    repo = ContactRepository(pg_session)

    c1 = repo.upsert_by_phone_append_sync(
        phone="15551119998",
        name="Sync First",
        information="Info A",
    )
    pg_session.flush()

    c2 = repo.upsert_by_phone_append_sync(
        phone="15551119998",
        name="Sync Second",
        information="Info B",
    )
    pg_session.flush()

    assert c1.id == c2.id
    assert "Info A" in c2.information
    assert "Info B" in c2.information
