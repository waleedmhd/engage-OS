"""Payables schemas — request/response contracts for bills, payments, debit notes, ageing."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------- bill lines


class BillLineRequest(BaseModel):
    item_id: uuid.UUID | None = None
    description: str = Field(..., max_length=500)
    qty: Decimal = Field(default=Decimal("1.00"))
    unit_cost: Decimal = Field(default=Decimal("0.0000"))


class BillLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bill_id: uuid.UUID
    item_id: uuid.UUID | None = None
    description: str
    qty: Decimal
    unit_cost: Decimal
    line_total: Decimal
    tax_code_id: uuid.UUID | None = None
    tax_rate: Decimal
    tax_amount: Decimal


# ---------------------------------------------------------------- bills


class BillCreateRequest(BaseModel):
    supplier_id: uuid.UUID
    posting_date: date
    due_date: date
    currency_code: str = "AED"
    lines: list[BillLineRequest] = Field(..., min_length=1)
    po_id: uuid.UUID | None = None
    grn_id: uuid.UUID | None = None
    remarks: str | None = None


class BillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bill_no: str
    supplier_id: uuid.UUID
    po_id: uuid.UUID | None = None
    grn_id: uuid.UUID | None = None
    posting_date: date
    due_date: date
    currency_code: str
    fx_rate: Decimal
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    status: str
    je_id: uuid.UUID | None = None
    remarks: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    lines: list[BillLineResponse] = []


# ---------------------------------------------------------------- payments


class PaymentCreateRequest(BaseModel):
    supplier_id: uuid.UUID
    payment_date: date
    amount: Decimal = Field(..., gt=Decimal("0"))
    currency_code: str = "AED"
    payment_method: str = "bank_transfer"
    reference: str | None = None


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_no: str
    supplier_id: uuid.UUID
    payment_date: date
    amount: Decimal
    currency_code: str
    fx_rate: Decimal
    payment_method: str
    reference: str | None = None
    je_id: uuid.UUID | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PaymentAllocationRequest(BaseModel):
    bill_id: uuid.UUID
    amount: Decimal = Field(..., gt=Decimal("0"))


class AllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_id: uuid.UUID
    bill_id: uuid.UUID
    amount: Decimal


# ---------------------------------------------------------------- debit notes


class DebitNoteCreateRequest(BaseModel):
    supplier_id: uuid.UUID
    bill_id: uuid.UUID | None = None
    date: date
    amount: Decimal = Field(..., gt=Decimal("0"))
    reason: str = "other"
    currency_code: str = "AED"


class DebitNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    debit_note_no: str
    supplier_id: uuid.UUID
    bill_id: uuid.UUID | None = None
    date: date
    amount: Decimal
    reason: str
    currency_code: str
    fx_rate: Decimal
    je_id: uuid.UUID | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------- ageing


class AgeingBucket(BaseModel):
    label: str
    count: int
    total_amount: Decimal


class AgeingResponse(BaseModel):
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = None
    buckets: list[AgeingBucket]
    total_outstanding: Decimal
