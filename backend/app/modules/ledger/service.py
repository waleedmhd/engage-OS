"""Ledger service layer — accounts, journals, trial balance, fiscal periods.

Services own business logic; routers own HTTP concerns. All mutations flush
only — the router commits the unit of work (Msg-C4).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.money import money, money_sum, money_zero
from app.modules.ledger.constants import (
    NORMAL_SIDE_MAP,
    AccountNormalSide,
    AccountType,
    PeriodStatus,
)
from app.modules.ledger.models import Account, FiscalPeriod, JournalEntry
from app.modules.ledger.posting import PostingError, PostingService
from app.modules.ledger.repository import (
    AccountRepository,
    FiscalPeriodRepository,
    JournalEntryRepository,
    JournalLineRepository,
)
from app.modules.ledger.schemas import (
    AccountCreateRequest,
    AccountResponse,
    FiscalPeriodResponse,
    JournalEntryCreateRequest,
    JournalEntryResponse,
    JournalLineResponse,
    TrialBalanceResponse,
    TrialBalanceRow,
)


class AccountService:
    """Chart of Accounts CRUD."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AccountRepository(session)

    async def create(self, request: AccountCreateRequest) -> AccountResponse:
        existing = await self._repo.get_by_code(request.code)
        if existing is not None:
            raise ValidationError(
                f"Account code '{request.code}' already exists.",
                details={"code": "duplicate_account_code"},
            )
        account = await self._repo.create(
            code=request.code,
            name=request.name,
            type=request.type,
            normal_side=request.normal_side,
            parent_id=request.parent_id,
            is_control=request.is_control,
            is_postable=request.is_postable,
            description=request.description,
        )
        return AccountResponse.model_validate(account)

    async def get(self, account_id: uuid.UUID) -> AccountResponse:
        account = await self._repo.get_or_404(account_id)
        return AccountResponse.model_validate(account)

    async def list_active(self) -> list[AccountResponse]:
        accounts = await self._repo.list_active()
        return [AccountResponse.model_validate(a) for a in accounts]


class JournalService:
    """Thin service wrappers around PostingService.

    PostingService validates and writes; this service adds the convenience
    of fetching entries with lines and converting schemas.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._entry_repo = JournalEntryRepository(session)

    async def post_entry(
        self, request: JournalEntryCreateRequest, *, actor_id: uuid.UUID
    ) -> JournalEntryResponse:
        posting = PostingService(self._session)
        entry = await posting.post(request, actor_id=actor_id)
        return _entry_to_response(entry)

    async def reverse_entry(
        self, entry_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> JournalEntryResponse:
        posting = PostingService(self._session)
        reversal = await posting.reverse(entry_id, actor_id=actor_id)
        return _entry_to_response(reversal)

    async def get_entry(self, entry_id: uuid.UUID) -> JournalEntryResponse:
        entry = await self._entry_repo.get_with_lines(entry_id)
        if entry is None:
            raise NotFoundError(f"Journal entry {entry_id} not found")
        return _entry_to_response(entry)

    async def list_posted(
        self,
        account_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JournalEntryResponse]:
        entries = await self._entry_repo.list_posted(
            account_id=account_id, limit=limit, offset=offset
        )
        return [_entry_to_response(e) for e in entries]


class TrialBalanceService:
    """Compute trial balance as of a given date."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._account_repo = AccountRepository(session)
        self._line_repo = JournalLineRepository(session)

    async def build(self, as_of_date: date) -> TrialBalanceResponse:
        # Determine fiscal year start from settings.
        from app.modules.settings.constants import SETTING_ERP_FISCAL_YEAR_START_MONTH
        from app.modules.settings.repository import SettingsRepository

        settings_repo = SettingsRepository(self._session)
        fy_setting = await settings_repo.get(SETTING_ERP_FISCAL_YEAR_START_MONTH)
        fy_start_month: int = 1
        if fy_setting is not None and isinstance(fy_setting.value, dict):
            fy_start_month = int(fy_setting.value.get("month", 1))

        # Fiscal year that contains as_of_date.
        fiscal_year = as_of_date.year
        fy_start = date(fiscal_year, fy_start_month, 1)
        if as_of_date < fy_start:
            fiscal_year -= 1
            fy_start = date(fiscal_year, fy_start_month, 1)
        _fy_end = date(fiscal_year + 1, fy_start_month, 1) - timedelta(days=1)

        accounts = await self._account_repo.list_active()

        rows: list[TrialBalanceRow] = []
        total_dr = money_zero()
        total_cr = money_zero()

        for account in accounts:
            # Opening: from the beginning of time up to the day before fy_start.
            opening_dr, opening_cr = await self._line_repo.sum_by_account(
                account.id,
                to_date=fy_start - timedelta(days=1),
            )

            # Period activity: fy_start through as_of_date.
            period_dr, period_cr = await self._line_repo.sum_by_account(
                account.id,
                from_date=fy_start,
                to_date=as_of_date,
            )

            # Closing = opening + period activity.
            closing_dr = money(opening_dr + period_dr)
            closing_cr = money(opening_cr + period_cr)

            # Normal-side determines which columns show the balance.
            # Debit-normal: Dr - Cr (positive in closing_dr, zero in closing_cr
            #   if Dr >= Cr, else zero in closing_dr, Cr - Dr in closing_cr).
            # Credit-normal: Cr - Dr (same logic reversed).
            normal_side = NORMAL_SIDE_MAP.get(AccountType(account.type))
            display_dr = money_zero()
            display_cr = money_zero()

            if normal_side == AccountNormalSide.DEBIT:
                net = money(closing_dr - closing_cr)
                if net >= 0:
                    display_dr = net
                else:
                    display_cr = money(-net)
            else:
                net = money(closing_cr - closing_dr)
                if net >= 0:
                    display_cr = net
                else:
                    display_dr = money(-net)

            rows.append(
                TrialBalanceRow(
                    account_code=account.code,
                    account_name=account.name,
                    account_type=account.type,
                    opening_dr=opening_dr,
                    opening_cr=opening_cr,
                    period_dr=period_dr,
                    period_cr=period_cr,
                    closing_dr=display_dr,
                    closing_cr=display_cr,
                )
            )

            total_dr += display_dr
            total_cr += display_cr

        return TrialBalanceResponse(
            as_of_date=as_of_date,
            rows=rows,
            total_dr=money(total_dr),
            total_cr=money(total_cr),
            difference=money(total_dr - total_cr),
        )


class PeriodService:
    """Fiscal period lifecycle management."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = FiscalPeriodRepository(session)

    async def list_periods(self) -> list[FiscalPeriodResponse]:
        from sqlalchemy import select as sa_select

        result = await self._session.execute(
            sa_select(FiscalPeriod).order_by(
                FiscalPeriod.fiscal_year.asc(), FiscalPeriod.month.asc()
            )
        )
        periods = result.scalars().all()
        return [FiscalPeriodResponse.model_validate(p) for p in periods]

    async def close_period(self, period_id: uuid.UUID) -> FiscalPeriodResponse:
        period = await self._repo.get_or_404(period_id)
        if period.status == PeriodStatus.CLOSED.value:
            raise ValidationError(
                f"Period {period.fiscal_year}-{period.month:02d} is already closed.",
                details={"code": "period_already_closed"},
            )
        if period.status == PeriodStatus.LOCKED.value:
            raise ValidationError(
                f"Period {period.fiscal_year}-{period.month:02d} is locked and cannot be closed.",
                details={"code": "period_locked"},
            )
        period.status = PeriodStatus.CLOSED.value
        await self._session.flush()

        from app.core.events import FinanceEvents, emit_event

        emit_event(
            FinanceEvents.PERIOD_CLOSED,
            period_id=str(period.id),
            fiscal_year=period.fiscal_year,
            month=period.month,
        )
        return FiscalPeriodResponse.model_validate(period)

    async def reopen_period(self, period_id: uuid.UUID) -> FiscalPeriodResponse:
        period = await self._repo.get_or_404(period_id)
        if period.status != PeriodStatus.CLOSED.value:
            raise ValidationError(
                f"Period {period.fiscal_year}-{period.month:02d} is not closed.",
                details={"code": "period_not_closed"},
            )
        period.status = PeriodStatus.OPEN.value
        await self._session.flush()

        from app.core.events import FinanceEvents, emit_event

        emit_event(
            FinanceEvents.PERIOD_REOPENED,
            period_id=str(period.id),
            fiscal_year=period.fiscal_year,
            month=period.month,
        )
        return FiscalPeriodResponse.model_validate(period)


# ----------------------------------------------------------------- helpers


def _entry_to_response(entry: JournalEntry) -> JournalEntryResponse:
    return JournalEntryResponse(
        id=entry.id,
        entry_no=entry.entry_no,
        posting_date=entry.posting_date,
        period_id=entry.period_id,
        voucher_type=entry.voucher_type,
        description=entry.description,
        source_type=entry.source_type,
        source_id=entry.source_id,
        status=entry.status,
        posted_at=entry.posted_at,
        is_opening=entry.is_opening,
        is_system_generated=entry.is_system_generated,
        user_remark=entry.user_remark,
        system_remark=entry.system_remark,
        created_at=entry.created_at,
        lines=[
            JournalLineResponse(
                id=line.id,
                account_id=line.account_id,
                description=line.description,
                dr=line.dr,
                cr=line.cr,
                currency_code=line.currency_code,
                fx_rate=line.fx_rate,
                dr_base=line.dr_base,
                cr_base=line.cr_base,
                party_type=line.party_type,
                party_id=line.party_id,
            )
            for line in (entry.lines if entry.lines else [])
        ],
    )
