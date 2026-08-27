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
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.db.repository import BaseRepository
from app.modules.contacts.models import Contact

_SORTABLE_COLUMNS = ("last_interaction_at", "created_at", "name")


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
        information: str | None = None,
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

        ``information`` is only set when the contact is new OR the existing
        row has no information yet — AI never overwrites a value that was
        already seeded (by AI or a human). Humans can always edit via PATCH.
        """
        # Attempt 1: fast path — the row already exists.
        existing = await self.get_by_phone(phone)
        if existing is not None:
            if information and not existing.information:
                existing.information = information
                await self.session.flush()
            return existing

        # Attempt 2: optimistic INSERT inside a SAVEPOINT.
        try:
            async with self.session.begin_nested():  # → SAVEPOINT
                contact = await self.create(
                    phone=phone, name=name, information=information
                )
            return contact
        except IntegrityError:  # pragma: no cover — concurrent-insert race
            pass

        existing = await self.get_by_phone(phone)  # pragma: no cover
        if existing is None:  # pragma: no cover
            raise ConflictError(
                f"Contact with phone {phone!r} was created concurrently "
                "but could not be retrieved. The record may have been "
                "deleted immediately after creation."
            )

        return existing  # pragma: no cover

    async def upsert_by_phone_append(
        self,
        phone: str,
        name: str | None = None,
        information: str | None = None,
    ) -> Contact:
        """Like upsert_by_phone, but APPENDS information with a separator.

        Repeated calls accumulate context rather than leaving the field
        frozen after first write. The existing "never overwrite" invariant
        is preserved — concurrent human edits via PATCH override fully.
        Callers that only set on first write should use upsert_by_phone.
        """
        existing = await self.get_by_phone(phone)
        if existing is not None:
            # Only set name if the contact has no name yet — never
            # overwrite a name that was set by a human or prior AI run.
            if name and not existing.name:
                existing.name = name
            if information:
                if existing.information:
                    existing.information = (
                        existing.information + "\n\n---\n\n" + information
                    )
                else:
                    existing.information = information
                await self.session.flush()
            return existing

        try:
            async with self.session.begin_nested():
                contact = await self.create(
                    phone=phone, name=name, information=information
                )
            return contact
        except IntegrityError:  # pragma: no cover — concurrent-insert race
            pass

        existing = await self.get_by_phone(phone)  # pragma: no cover
        if existing is None:  # pragma: no cover
            raise ConflictError(
                f"Contact with phone {phone!r} was created concurrently "
                "but could not be retrieved."
            )
        if name and not existing.name:  # pragma: no cover
            existing.name = name
        if information:  # pragma: no cover
            if existing.information:
                existing.information = (
                    existing.information + "\n\n---\n\n" + information
                )
            else:
                existing.information = information
            await self.session.flush()
        return existing  # pragma: no cover

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

    async def list_with_filters(
        self,
        *,
        q: str | None = None,
        status: list[str] | None = None,
        assigned_agent_id: uuid.UUID | None = None,
        tag_ids: list[uuid.UUID] | None = None,
        has_assigned_agent: bool | None = None,
        ai_assigned: bool | None = None,
        order_by: str = "-last_interaction_at",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Contact], int]:
        """
        Composite filter + paginated list. Returns (items, total).

        Uses ILIKE for `q`; the trigram indexes added in migration 0002
        make these queries index-eligible for substring matches.
        """
        clauses: list[Any] = []
        if q:
            pattern = f"%{q}%"
            clauses.append(
                sa.or_(
                    Contact.name.ilike(pattern),
                    Contact.phone.ilike(pattern),
                    Contact.company.ilike(pattern),
                )
            )
        if status:
            clauses.append(Contact.status.in_(status))
        if assigned_agent_id is not None:
            clauses.append(Contact.assigned_agent_id == assigned_agent_id)
        if has_assigned_agent is True:
            clauses.append(Contact.assigned_agent_id.is_not(None))
        elif has_assigned_agent is False:
            clauses.append(Contact.assigned_agent_id.is_(None))
        if ai_assigned is not None:
            clauses.append(Contact.ai_assigned == ai_assigned)
        if tag_ids:
            from app.modules.categorization.models import ContactTag

            clauses.append(
                Contact.id.in_(
                    sa.select(ContactTag.contact_id).where(ContactTag.tag_id.in_(tag_ids))
                )
            )

        from sqlalchemy.orm import selectinload

        from app.modules.categorization.models import ContactTag

        stmt = sa.select(Contact)
        count_stmt = sa.select(sa.func.count()).select_from(Contact)
        if clauses:
            stmt = stmt.where(*clauses)
            count_stmt = count_stmt.where(*clauses)

        # Eager-load the contact's tags (and the resolved Tag rows) so the list
        # response can render tag chips without an N+1 per row.
        stmt = stmt.options(
            selectinload(Contact.contact_tags).selectinload(ContactTag.tag)
        )
        stmt = stmt.order_by(*_resolve_order(order_by)).limit(limit).offset(offset)

        rows_result = await self.session.execute(stmt)
        rows = list(rows_result.scalars().all())
        total_result = await self.session.execute(count_stmt)
        total = int(total_result.scalar_one())
        return rows, total

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
        ts = when or datetime.now(tz=UTC)
        await self.session.execute(
            sa.update(Contact)
            .where(Contact.id == contact_id)
            .values(
                last_interaction_at=ts,
                conversation_count=Contact.conversation_count + 1,
            )
        )

    async def touch_last_contacted(
        self,
        contact_id: uuid.UUID,
        when: datetime | None = None,
    ) -> None:
        """Set last_contacted_at to the given datetime (or now)."""
        ts = when or datetime.now(tz=UTC)
        await self.session.execute(
            sa.update(Contact)
            .where(Contact.id == contact_id)
            .values(last_contacted_at=ts)
        )

    async def touch_last_inbound(
        self,
        contact_id: uuid.UUID,
        when: datetime | None = None,
    ) -> None:
        """Set last_inbound_at to the given datetime (or now)."""
        ts = when or datetime.now(tz=UTC)
        await self.session.execute(
            sa.update(Contact)
            .where(Contact.id == contact_id)
            .values(last_inbound_at=ts)
        )

    # ------------------------------------------------------ sync counterparts
    # Used by Celery tasks that operate with a synchronous session.

    def get_by_id_sync(self, contact_id: uuid.UUID) -> Contact | None:
        """Synchronous lookup by primary key — for Celery task usage."""
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        return session.get(Contact, contact_id)

    def touch_last_contacted_sync(
        self,
        contact_id: uuid.UUID,
        when: datetime | None = None,
    ) -> None:
        """Sync version of touch_last_contacted for Celery tasks."""
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        ts = when or datetime.now(tz=UTC)
        session.execute(
            sa.update(Contact)
            .where(Contact.id == contact_id)
            .values(last_contacted_at=ts)
        )

    def touch_last_inbound_sync(
        self,
        contact_id: uuid.UUID,
        when: datetime | None = None,
    ) -> None:
        """Sync version of touch_last_inbound for Celery tasks."""
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        ts = when or datetime.now(tz=UTC)
        session.execute(
            sa.update(Contact)
            .where(Contact.id == contact_id)
            .values(last_inbound_at=ts)
        )

    def transition_status_sync(
        self,
        contact_id: uuid.UUID,
        new_status: str,
    ) -> None:
        """Set contact status directly — used from Celery tasks."""
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        session.execute(
            sa.update(Contact)
            .where(Contact.id == contact_id)
            .values(status=new_status)
        )

    def set_do_not_contact_sync(
        self,
        contact_id: uuid.UUID,
        value: bool,
    ) -> None:
        """Set the do_not_contact flag (engagement policy §2 opt-out)."""
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        session.execute(
            sa.update(Contact)
            .where(Contact.id == contact_id)
            .values(do_not_contact=value)
        )

    def upsert_by_phone_sync(
        self,
        phone: str,
        name: str | None = None,
        information: str | None = None,
    ) -> Contact:
        """
        Synchronous version of upsert_by_phone for use in Celery tasks.
        Same SAVEPOINT-based race handling.

        ``information`` is only set when the contact is new OR the existing
        row has no information yet — AI never overwrites a value that was
        already seeded.
        """
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]

        existing = session.execute(
            sa.select(Contact).where(Contact.phone == phone)
        ).scalar_one_or_none()
        if existing is not None:
            if information and not existing.information:
                existing.information = information
                session.flush()
            return existing

        try:
            with session.begin_nested():
                contact = Contact(phone=phone, name=name, information=information)
                session.add(contact)
                session.flush()
            return contact
        except IntegrityError:  # pragma: no cover — concurrent-insert race
            pass

        existing = session.execute(  # pragma: no cover
            sa.select(Contact).where(Contact.phone == phone)
        ).scalar_one_or_none()

        if existing is None:  # pragma: no cover
            raise ConflictError(
                f"Contact with phone {phone!r} could not be upserted "
                "due to a concurrent delete."
            )
        return existing  # pragma: no cover

    def upsert_by_phone_append_sync(
        self,
        phone: str,
        name: str | None = None,
        information: str | None = None,
    ) -> Contact:
        """Synchronous version of upsert_by_phone_append."""
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]

        existing = session.execute(
            sa.select(Contact).where(Contact.phone == phone)
        ).scalar_one_or_none()
        if existing is not None:
            if name and not existing.name:
                existing.name = name
            if information:
                if existing.information:
                    existing.information = (
                        existing.information + "\n\n---\n\n" + information
                    )
                else:
                    existing.information = information
                session.flush()
            return existing

        try:
            with session.begin_nested():
                contact = Contact(phone=phone, name=name, information=information)
                session.add(contact)
                session.flush()
            return contact
        except IntegrityError:  # pragma: no cover — concurrent-insert race
            pass

        existing = session.execute(  # pragma: no cover
            sa.select(Contact).where(Contact.phone == phone)
        ).scalar_one_or_none()
        if existing is None:  # pragma: no cover
            raise ConflictError(
                f"Contact with phone {phone!r} could not be upserted "
                "due to a concurrent delete."
            )
        if name and not existing.name:  # pragma: no cover
            existing.name = name
        if information:  # pragma: no cover
            if existing.information:
                existing.information = (
                    existing.information + "\n\n---\n\n" + information
                )
            else:
                existing.information = information
            session.flush()
        return existing  # pragma: no cover


def _resolve_order(order_by: str) -> list[Any]:
    """Map a `-prefix` order string to SQLAlchemy ORDER BY clauses.

    Whitelist: last_interaction_at, created_at, name. Anything else falls
    back to last_interaction_at desc nullslast for safety.
    """
    desc = order_by.startswith("-")
    name = order_by.lstrip("-")
    if name not in _SORTABLE_COLUMNS:
        return [Contact.last_interaction_at.desc().nullslast(), Contact.id.desc()]
    col = getattr(Contact, name)
    expr = col.desc().nullslast() if desc else col.asc().nullslast()
    # Tie-breaker for stable pagination
    return [expr, Contact.id.desc()]
