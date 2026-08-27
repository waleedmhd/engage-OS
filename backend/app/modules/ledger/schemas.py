"""Ledger schemas — request/response contracts for accounts, journals, periods."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------- account ----


class AccountCreateRequest(BaseModel):
    code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=200)
    type: str
    normal_side: str = "debit"
    parent_id: uuid.UUID | None = None
    is_control: bool = False
    is_postable: bool = True
    description: str | None = None


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    type: str
    normal_side: str
    parent_id: uuid.UUID | None = None
    is_control: bool
    is_postable: bool
    is_active: bool
    description: str | None = None
    created_at: datetime | None = None


# ------------------------------------------------------------- journal -------


class JournalLineRequest(BaseModel):
    account_id: uuid.UUID
    description: str | None = None
    dr: Decimal = Field(default=Decimal("0.0000"))
    cr: Decimal = Field(default=Decimal("0.0000"))
    currency_code: str | None = None
    fx_rate: Decimal | None = None
    dr_base: Decimal = Field(default=Decimal("0.0000"))
    cr_base: Decimal = Field(default=Decimal("0.0000"))
    party_type: str | None = None
    party_id: uuid.UUID | None = None


class JournalEntryCreateRequest(BaseModel):
    posting_date: date
    description: str | None = None
    voucher_type: str = "journal_entry"
    lines: list[JournalLineRequest] = Field(..., min_length=2)
    cheque_no: str | None = None
    cheque_date: date | None = None
    is_opening: bool = False
    user_remark: str | None = None


class JournalLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    description: str | None = None
    dr: Decimal
    cr: Decimal
    currency_code: str | None = None
    fx_rate: Decimal | None = None
    dr_base: Decimal
    cr_base: Decimal
    party_type: str | None = None
    party_id: uuid.UUID | None = None


class JournalEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_no: str
    posting_date: date
    period_id: uuid.UUID | None = None
    voucher_type: str
    description: str | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    status: str
    posted_at: datetime | None = None
    is_opening: bool
    is_system_generated: bool
    user_remark: str | None = None
    system_remark: str | None = None
    created_at: datetime | None = None
    lines: list[JournalLineResponse] = []


# ------------------------------------------------------------- period --------


class FiscalPeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fiscal_year: int
    month: int
    start_date: date
    end_date: date
    status: str


class PeriodCloseRequest(BaseModel):
    period_id: uuid.UUID


class PeriodReopenRequest(BaseModel):
    period_id: uuid.UUID


# ------------------------------------------------------- trial balance -------


class TrialBalanceRow(BaseModel):
    account_code: str
    account_name: str
    account_type: str
    opening_dr: Decimal
    opening_cr: Decimal
    period_dr: Decimal
    period_cr: Decimal
    closing_dr: Decimal
    closing_cr: Decimal


class TrialBalanceResponse(BaseModel):
    as_of_date: date
    rows: list[TrialBalanceRow]
    total_dr: Decimal
    total_cr: Decimal
    difference: Decimal
