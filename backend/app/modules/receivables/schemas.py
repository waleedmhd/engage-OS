"""Receivables request/response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.receivables.constants import (
    CreditNoteReason,
    CreditNoteStatus,
    InvoiceStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.schemas.common import Page


# ------------------------------------------------------------------- Invoice Lines


class InvoiceLineRequest(BaseModel):
    """A single line item in a create/update invoice request."""

    item_id: uuid.UUID | None = None
    description: str = Field(default="", max_length=500)
    qty: Decimal = Field(..., ge=0)
    unit_price: Decimal = Field(..., ge=0)
    tax_code_id: uuid.UUID | None = None
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("qty", mode="before")
    @classmethod
    def _coerce_qty(cls, v: object) -> Decimal:
        from app.core.money import qty as quantize_qty

        return quantize_qty(str(v))

    @field_validator("unit_price", "tax_rate", mode="before")
    @classmethod
    def _coerce_money(cls, v: object) -> Decimal:
        from app.core.money import money

        return money(str(v))


class InvoiceLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    item_id: uuid.UUID | None = None
    description: str
    qty: Decimal
    unit_price: Decimal
    line_total: Decimal
    tax_code_id: uuid.UUID | None = None
    tax_rate: Decimal
    tax_amount: Decimal


# ----------------------------------------------------------------------- Invoices


class InvoiceCreateRequest(BaseModel):
    customer_id: uuid.UUID
    posting_date: date
    due_date: date
    currency_code: str = Field(default="AED", min_length=3, max_length=3)
    lines: list[InvoiceLineRequest] = Field(..., min_length=1)
    remarks: str | None = None

    @field_validator("due_date")
    @classmethod
    def _due_after_posting(cls, v: date, info) -> date:
        posting_date = info.data.get("posting_date")
        if posting_date is not None and v < posting_date:
            raise ValueError("due_date must be on or after posting_date")
        return v


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str
    customer_id: uuid.UUID
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
    created_at: datetime
    updated_at: datetime
    lines: list[InvoiceLineResponse] = []


# ----------------------------------------------------------------------- Payments


class PaymentCreateRequest(BaseModel):
    customer_id: uuid.UUID
    payment_date: date
    amount: Decimal = Field(..., gt=0)
    currency_code: str = Field(default="AED", min_length=3, max_length=3)
    payment_method: str = Field(default=PaymentMethod.BANK_TRANSFER.value)
    reference: str | None = Field(default=None, max_length=200)

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> Decimal:
        from app.core.money import money

        return money(str(v))

    @field_validator("payment_method")
    @classmethod
    def _check_method(cls, v: str) -> str:
        valid = {e.value for e in PaymentMethod}
        if v not in valid:
            raise ValueError(f"payment_method must be one of {sorted(valid)}")
        return v


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_no: str
    customer_id: uuid.UUID
    payment_date: date
    amount: Decimal
    currency_code: str
    fx_rate: Decimal
    payment_method: str
    reference: str | None = None
    je_id: uuid.UUID | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class PaymentAllocationRequest(BaseModel):
    invoice_id: uuid.UUID
    amount: Decimal = Field(..., gt=0)

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> Decimal:
        from app.core.money import money

        return money(str(v))


class AllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_id: uuid.UUID
    invoice_id: uuid.UUID
    amount: Decimal


# ------------------------------------------------------------------- Credit Notes


class CreditNoteCreateRequest(BaseModel):
    customer_id: uuid.UUID
    invoice_id: uuid.UUID | None = None
    date: date
    amount: Decimal = Field(..., gt=0)
    reason: str = Field(default=CreditNoteReason.OTHER.value)
    currency_code: str = Field(default="AED", min_length=3, max_length=3)
    remarks: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> Decimal:
        from app.core.money import money

        return money(str(v))

    @field_validator("reason")
    @classmethod
    def _check_reason(cls, v: str) -> str:
        valid = {e.value for e in CreditNoteReason}
        if v not in valid:
            raise ValueError(f"reason must be one of {sorted(valid)}")
        return v


class CreditNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    credit_note_no: str
    customer_id: uuid.UUID
    invoice_id: uuid.UUID | None = None
    date: date
    amount: Decimal
    reason: str
    currency_code: str
    fx_rate: Decimal
    je_id: uuid.UUID | None = None
    status: str
    remarks: str | None = None
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------- Ageing


class AgeingBucket(BaseModel):
    label: str
    count: int
    total: Decimal


class AgeingResponse(BaseModel):
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    buckets: list[AgeingBucket]
    total_outstanding: Decimal


# ------------------------------------------------------------ CRM Inbox Integration


class ContactErpSummary(BaseModel):
    """Returned by GET /contacts/{id}/erp-summary for the CRM inbox sidebar."""

    outstanding_ar_balance: Decimal
    total_revenue: Decimal
    last_invoices: list[InvoiceResponse]
