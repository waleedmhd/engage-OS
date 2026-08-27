"""ERP reporting endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession
from app.core.dependencies import require_permission
from app.modules.erp_reporting.schemas import (
    BalanceSheetResponse,
    MarginResponse,
    PLReportResponse,
    TrialBalanceReportResponse,
)
from app.modules.erp_reporting.service import ReportService

_PC = "erp_rep"

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/trial-balance",
    response_model=TrialBalanceReportResponse,
)
async def trial_balance(
    session: DbSession,
    as_of_date: date = Query(...),
    _user=Depends(require_permission(f"{_PC}.statements.view")),
) -> TrialBalanceReportResponse:
    """Trial balance — SUM dr/cr per account as of a given date."""
    service = ReportService(session)
    return await service.build_trial_balance(as_of_date)


@router.get(
    "/profit-and-loss",
    response_model=PLReportResponse,
)
async def profit_and_loss(
    session: DbSession,
    fiscal_year: int = Query(...),
    _user=Depends(require_permission(f"{_PC}.statements.view")),
) -> PLReportResponse:
    """Profit & Loss — revenue - cogs - opex for the fiscal year."""
    service = ReportService(session)
    return await service.build_pl(fiscal_year)


@router.get(
    "/balance-sheet",
    response_model=BalanceSheetResponse,
)
async def balance_sheet(
    session: DbSession,
    as_of_date: date = Query(...),
    _user=Depends(require_permission(f"{_PC}.statements.view")),
) -> BalanceSheetResponse:
    """Balance sheet — assets = liabilities + equity as of a given date."""
    service = ReportService(session)
    return await service.build_balance_sheet(as_of_date)


@router.get(
    "/gross-margin",
    response_model=MarginResponse,
)
async def gross_margin(
    session: DbSession,
    fiscal_year: int = Query(...),
    _user=Depends(require_permission(f"{_PC}.margin.view")),
) -> MarginResponse:
    """Gross margin by item/customer for the fiscal year."""
    service = ReportService(session)
    return await service.build_margin(fiscal_year)
