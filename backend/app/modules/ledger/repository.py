"""Ledger repositories — accounts, periods, journal entries/lines."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import BaseRepository
from app.modules.ledger.constants import JournalStatus, PeriodStatus
from app.modules.ledger.models import (
    Account,
    FiscalPeriod,
    JournalEntry,
    JournalLine,
    TaxCode,
)


class AccountRepository(BaseRepository[Account]):
    model = Account

    async def get_by_code(self, code: str) -> Account | None:
        result = await self.session.execute(
            sa.select(Account).where(Account.code == code)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Account]:
        result = await self.session.execute(
            sa.select(Account)
            .where(Account.is_active == True)  # noqa: E712
            .order_by(Account.code)
        )
        return list(result.scalars().all())


class FiscalPeriodRepository(BaseRepository[FiscalPeriod]):
    model = FiscalPeriod

    async def get_open_period(self, posting_date: date) -> FiscalPeriod | None:
        """Return the open period that contains *posting_date*."""
        from datetime import date as date_type

        result = await self.session.execute(
            sa.select(FiscalPeriod).where(
                FiscalPeriod.start_date <= posting_date,
                FiscalPeriod.end_date >= posting_date,
                FiscalPeriod.status == PeriodStatus.OPEN.value,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_year_month(self, fiscal_year: int, month: int) -> FiscalPeriod | None:
        result = await self.session.execute(
            sa.select(FiscalPeriod).where(
                FiscalPeriod.fiscal_year == fiscal_year,
                FiscalPeriod.month == month,
            )
        )
        return result.scalar_one_or_none()


class JournalEntryRepository(BaseRepository[JournalEntry]):
    model = JournalEntry

    async def get_by_entry_no(self, entry_no: str) -> JournalEntry | None:
        result = await self.session.execute(
            sa.select(JournalEntry).where(JournalEntry.entry_no == entry_no)
        )
        return result.scalar_one_or_none()

    async def get_with_lines(self, entry_id: uuid.UUID) -> JournalEntry | None:
        from sqlalchemy.orm import joinedload

        result = await self.session.execute(
            sa.select(JournalEntry)
            .options(joinedload(JournalEntry.lines))
            .where(JournalEntry.id == entry_id)
        )
        return result.unique().scalar_one_or_none()

    async def list_posted(
        self,
        *,
        account_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JournalEntry]:
        stmt = (
            sa.select(JournalEntry)
            .where(JournalEntry.status == JournalStatus.POSTED.value)
            .order_by(JournalEntry.posting_date.desc(), JournalEntry.created_at.desc())
        )
        if account_id is not None:
            stmt = stmt.where(
                JournalEntry.id.in_(
                    sa.select(JournalLine.entry_id).where(
                        JournalLine.account_id == account_id
                    )
                )
            )
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class JournalLineRepository(BaseRepository[JournalLine]):
    model = JournalLine

    async def sum_by_account(
        self,
        account_id: uuid.UUID,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Return (total_dr, total_cr) for *account_id* in the given date range.

        The join to ``journal_entries`` must be explicit. Filtering the status
        through ``JournalLine.entry.has(...)`` compiles to an EXISTS subquery
        and leaves ``journal_entries`` out of the FROM clause, so the
        ``posting_date`` predicates below would add it unjoined — a cartesian
        product that multiplied every line by the number of posted entries in
        range, and matched the dates against any entry rather than the line's
        own.
        """
        stmt = (
            sa.select(
                sa.func.coalesce(sa.func.sum(JournalLine.dr_base), 0),
                sa.func.coalesce(sa.func.sum(JournalLine.cr_base), 0),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.account_id == account_id,
                JournalEntry.status == JournalStatus.POSTED.value,
            )
        )
        if from_date is not None:
            stmt = stmt.where(JournalEntry.posting_date >= from_date)
        if to_date is not None:
            stmt = stmt.where(JournalEntry.posting_date <= to_date)

        result = await self.session.execute(stmt)
        row = result.one()
        return Decimal(str(row[0])), Decimal(str(row[1]))


class TaxCodeRepository(BaseRepository[TaxCode]):
    model = TaxCode

    async def get_by_code(self, code: str) -> TaxCode | None:
        result = await self.session.execute(
            sa.select(TaxCode).where(TaxCode.code == code)
        )
        return result.scalar_one_or_none()
