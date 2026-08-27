"""Ledger REST endpoints — accounts, journals, trial balance, fiscal periods.

Every endpoint requires a specific permission. The router commits the session
after mutating operations; the service only flushes.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUserDB, DbSession
from app.core.dependencies import require_permission
from app.modules.ledger.posting import PostingError
from app.modules.ledger.schemas import (
    AccountCreateRequest,
    AccountResponse,
    FiscalPeriodResponse,
    JournalEntryCreateRequest,
    JournalEntryResponse,
    PeriodCloseRequest,
    PeriodReopenRequest,
    TrialBalanceResponse,
)
from app.modules.ledger.service import (
    AccountService,
    JournalService,
    PeriodService,
    TrialBalanceService,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])


# --------------------------------------------------------------- accounts ----


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    db: DbSession,
    _user=Depends(require_permission("erp_fin.coa.manage")),
) -> list[AccountResponse]:
    return await AccountService(db).list_active()


@router.post(
    "/accounts",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_account(
    payload: AccountCreateRequest,
    db: DbSession,
    _user=Depends(require_permission("erp_fin.coa.manage")),
) -> AccountResponse:
    result = await AccountService(db).create(payload)
    await db.commit()
    return result


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: uuid.UUID,
    db: DbSession,
    _user=Depends(require_permission("erp_fin.coa.manage")),
) -> AccountResponse:
    return await AccountService(db).get(account_id)


# ----------------------------------------------------------- journal entries --


@router.post(
    "/journals",
    response_model=JournalEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_journal(
    payload: JournalEntryCreateRequest,
    db: DbSession,
    current_user=Depends(require_permission("erp_fin.journal.post")),
) -> JournalEntryResponse:
    try:
        result = await JournalService(db).post_entry(payload, actor_id=current_user.id)
    except PostingError as exc:
        raise exc
    await db.commit()
    return result


@router.get("/journals", response_model=list[JournalEntryResponse])
async def list_journals(
    db: DbSession,
    account_id: uuid.UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user=Depends(require_permission("erp_fin.journal.post")),
) -> list[JournalEntryResponse]:
    return await JournalService(db).list_posted(
        account_id=account_id, limit=limit, offset=offset
    )


@router.get("/journals/{entry_id}", response_model=JournalEntryResponse)
async def get_journal(
    entry_id: uuid.UUID,
    db: DbSession,
    _user=Depends(require_permission("erp_fin.journal.post")),
) -> JournalEntryResponse:
    return await JournalService(db).get_entry(entry_id)


@router.post(
    "/journals/{entry_id}/reverse",
    response_model=JournalEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reverse_journal(
    entry_id: uuid.UUID,
    db: DbSession,
    current_user=Depends(require_permission("erp_fin.journal.reverse")),
) -> JournalEntryResponse:
    try:
        result = await JournalService(db).reverse_entry(
            entry_id, actor_id=current_user.id
        )
    except PostingError as exc:
        raise exc
    await db.commit()
    return result


# ----------------------------------------------------------- trial balance ---


@router.get("/trial-balance", response_model=TrialBalanceResponse)
async def trial_balance(
    db: DbSession,
    as_of_date: Annotated[date, Query()],
    _user=Depends(require_permission("erp_rep.statements.view")),
) -> TrialBalanceResponse:
    return await TrialBalanceService(db).build(as_of_date)


# ------------------------------------------------------------ fiscal periods --


@router.get("/periods", response_model=list[FiscalPeriodResponse])
async def list_periods(
    db: DbSession,
    _user=Depends(require_permission("erp_fin.period.manage")),
) -> list[FiscalPeriodResponse]:
    return await PeriodService(db).list_periods()


@router.post("/periods/close", response_model=FiscalPeriodResponse)
async def close_period(
    payload: PeriodCloseRequest,
    db: DbSession,
    _user=Depends(require_permission("erp_fin.period.manage")),
) -> FiscalPeriodResponse:
    result = await PeriodService(db).close_period(payload.period_id)
    await db.commit()
    return result


@router.post("/periods/reopen", response_model=FiscalPeriodResponse)
async def reopen_period(
    payload: PeriodReopenRequest,
    db: DbSession,
    _user=Depends(require_permission("erp_fin.period.reopen")),
) -> FiscalPeriodResponse:
    result = await PeriodService(db).reopen_period(payload.period_id)
    await db.commit()
    return result
