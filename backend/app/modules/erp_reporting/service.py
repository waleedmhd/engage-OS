"""ERP reporting service — consumes ReportRepository and formats response DTOs."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import money
from app.modules.erp_reporting.repository import ReportRepository
from app.modules.erp_reporting.schemas import (
    BalanceSheetResponse,
    MarginItem,
    MarginResponse,
    PLReportResponse,
    TrialBalanceItem,
    TrialBalanceReportResponse,
)


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ReportRepository(session)

    # -------------------------------------------------------------- trial balance

    async def build_trial_balance(self, as_of_date: date) -> TrialBalanceReportResponse:
        rows = await self._repo.trial_balance(as_of_date)
        items = [TrialBalanceItem(**row) for row in rows]
        return TrialBalanceReportResponse(
            as_of_date=as_of_date,
            items=items,
        )

    # ----------------------------------------------------------- profit and loss

    async def build_pl(self, fiscal_year: int) -> PLReportResponse:
        data = await self._repo.profit_and_loss(fiscal_year)
        return PLReportResponse(
            fiscal_year=fiscal_year,
            revenue=data["revenue"],
            cogs=data["cogs"],
            gross_profit=data["gross_profit"],
            opex=data["opex"],
            net_profit=data["net_profit"],
        )

    # -------------------------------------------------------------- balance sheet

    async def build_balance_sheet(self, as_of_date: date) -> BalanceSheetResponse:
        data = await self._repo.balance_sheet(as_of_date)
        return BalanceSheetResponse(
            as_of_date=as_of_date,
            assets=data["assets"],
            liabilities=data["liabilities"],
            equity=data["equity"],
            total_liabilities_and_equity=data["total_liabilities_and_equity"],
        )

    # --------------------------------------------------------------- gross margin

    async def build_margin(self, fiscal_year: int) -> MarginResponse:
        rows = await self._repo.gross_margin(fiscal_year)
        items = [MarginItem(**row) for row in rows]
        total_revenue = money(sum(item.revenue for item in items))
        total_cogs = money(sum(item.cogs for item in items))
        total_margin = money(total_revenue - total_cogs)
        overall_margin_pct = money(
            (total_margin / total_revenue * 100) if total_revenue != 0 else 0
        )
        return MarginResponse(
            fiscal_year=fiscal_year,
            items=items,
            total_revenue=total_revenue,
            total_cogs=total_cogs,
            total_margin=total_margin,
            overall_margin_pct=overall_margin_pct,
        )
