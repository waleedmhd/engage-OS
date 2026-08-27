"""
app/modules/contacts/repository.py

Fixes applied:
  DB-I7  — upsert_by_phone's race recovery was not wrapped in a SAVEPOINT.
            Under READ COMMITTED isolation (PostgreSQL default), a concurrent
            INSERT from another transaction can cause a UniqueViolation on
            the contacts.phone UNIQUE index. If the exception was caught
            outside a SAVEPOINT, it poisoned the outer transaction —
            subsequent operations in the same session would fail with
            "InFailedSqlTransaction". The bare `assert existing is not None`
            also raised AssertionError (not a domain exception) if the
            concurrently inserted row was deleted between the except block
            and the SELECT.

            Fix:
            - The optimistic INSERT is wrapped in a SAVEPOINT via
              nested() (maps to SAVEPOINT/RELEASE SAVEPOINT in PostgreSQL).
            - On UniqueViolation the SAVEPOINT is rolled back (not the
              outer transaction), then we SELECT the existing row.
            - If the SELECT still returns None (row deleted concurrently),
              we raise a domain-level ConflictError rather than AssertionError.

  DB-M17 — touch_last_interaction(when) parameter was untyped.
            Fix: annotated as datetime.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.repository import BaseRepository
from app.modules.contacts.models import Contact


class ContactRepository(BaseRepository[Contact]):
    model = Contact

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_phone(self, phone: str) -> Contact | None:
        """Return a contact by E.164 phone number."""
        result = await self.session.execute(
            sa.select(Contact).where(Contact.phone == phone)
        )
        return result.scalar_one_or_none()

    async def upsert_by_phone(
        self,
        phone: str,
        name: str | None = None,
    ) -> Contact:
        """
        Return the contact with the given phone number, creating it if
        it does not exist.

        DB-I7 fix: the race between two concurrent inserts for the same
        phone number is handled correctly via SAVEPOINT:

          1. Attempt INSERT inside a SAVEPOINT.
          2. If UniqueViolation fires (concurrent insert won), roll back
             to the SAVEPOINT only — the outer transaction is unaffected.
          3. SELECT the existing row.
          4. If the row is gone again (deleted between steps 2 and 3),
             raise ConflictError (domain exception, not bare AssertionError).

        Under READ COMMITTED the SAVEPOINT approach is safe because each
        nested() call maps directly to PostgreSQL's SAVEPOINT/RELEASE
        SAVEPOINT / ROLLBACK TO SAVEPOINT commands.
        """
        # Attempt 1: fast path — the row already exists.
        existing = await self.get_by_phone(phone)
        if existing is not None:
            return existing

        # Attempt 2: optimistic INSERT inside a SAVEPOINT.
        try:
            async with self.session.begin_nested():  # → SAVEPOINT
                contact = await self.create(phone=phone, name=name)
            return contact
        except IntegrityError:
            # Concurrent insert won the UNIQUE race.
            # SAVEPOINT was rolled back by begin_nested().__aexit__,
            # outer transaction is clean.
            pass

        # Attempt 3: read the row the concurrent writer created.
        existing = await self.get_by_phone(phone)
        if existing is None:
            # The concurrent row was deleted between steps 2 and 3.
            # Raise a domain exception rather than a bare AssertionError.
            raise ConflictError(
                f"Contact with phone {phone!r} was created concurrently "
                "but could not be retrieved. The record may have been "
                "deleted immediately after creation."
            )

        return existing

    async def search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Contact]:
        """Full-text search on name, phone, and company."""
        pattern = f"%{query}%"
        result = await self.session.execute(
            sa.select(Contact)
            .where(
                sa.or_(
                    Contact.name.ilike(pattern),
                    Contact.phone.ilike(pattern),
                    Contact.company.ilike(pattern),
                )
            )
            .order_by(Contact.last_interaction_at.desc().nullslast())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def touch_last_interaction(
        self,
        contact_id: uuid.UUID,
        when: datetime | None = None,  # DB-M17 fix: typed as datetime
    ) -> None:
        """
        Update last_interaction_at to the given datetime (or now).

        DB-M17 fix: `when` is now annotated as `datetime | None` instead
        of being unannotated. This allows type checkers to catch callers
        passing e.g. strings or timestamps.
        """
        ts = when or datetime.now(tz=timezone.utc)
        await self.session.execute(
            sa.update(Contact)
            .where(Contact.id == contact_id)
            .values(
                last_interaction_at=ts,
                conversation_count=Contact.conversation_count + 1,
            )
        )

    # ------------------------------------------------------ sync counterparts
    # Used by Celery tasks that operate with a synchronous session.

    def upsert_by_phone_sync(
        self,
        phone: str,
        name: str | None = None,
    ) -> Contact:
        """
        Synchronous version of upsert_by_phone for use in Celery tasks.
        Same SAVEPOINT-based race handling.
        """
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]

        existing = session.execute(
            sa.select(Contact).where(Contact.phone == phone)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        try:
            with session.begin_nested():
                contact = Contact(phone=phone, name=name)
                session.add(contact)
                session.flush()
            return contact
        except IntegrityError:
            pass

        existing = session.execute(
            sa.select(Contact).where(Contact.phone == phone)
        ).scalar_one_or_none()

        if existing is None:
            raise ConflictError(
                f"Contact with phone {phone!r} could not be upserted "
                "due to a concurrent delete."
            )
        return existing
