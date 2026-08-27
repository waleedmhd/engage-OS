"""ERP reporting request/response schemas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


# -------------------------------------------------------------- Trial Balance


class TrialBalanceItem(BaseModel):
    account_code: str
    account_name: str
    account_type: str
    dr_total: Decimal
    cr_total: Decimal
    net_balance: Decimal


class TrialBalanceReportResponse(BaseModel):
    as_of_date: date
    items: list[TrialBalanceItem]


# ----------------------------------------------------------- Profit and Loss


class PLReportResponse(BaseModel):
    fiscal_year: int
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    opex: Decimal
    net_profit: Decimal


# -------------------------------------------------------------- Balance Sheet


class BalanceSheetResponse(BaseModel):
    as_of_date: date
    assets: Decimal
    liabilities: Decimal
    equity: Decimal
    total_liabilities_and_equity: Decimal


# --------------------------------------------------------------- Gross Margin


class MarginItem(BaseModel):
    entity_id: str | None = None
    entity_name: str
    entity_type: str
    revenue: Decimal
    cogs: Decimal
    margin: Decimal
    margin_pct: Decimal


class MarginResponse(BaseModel):
    fiscal_year: int
    items: list[MarginItem]
    total_revenue: Decimal
    total_cogs: Decimal
    total_margin: Decimal
    overall_margin_pct: Decimal
