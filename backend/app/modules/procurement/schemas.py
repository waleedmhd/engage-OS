"""Procurement request/response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ------------------------------------------------------------------- PO Lines


class POLineRequest(BaseModel):
    """A single line item in a create purchase order request."""

    item_id: uuid.UUID | None = None
    description: str = Field(default="", max_length=500)
    qty: Decimal = Field(..., ge=0)
    unit_cost: Decimal = Field(..., ge=0)

    @field_validator("qty", mode="before")
    @classmethod
    def _coerce_qty(cls, v: object) -> Decimal:
        from app.core.money import qty as quantize_qty

        return quantize_qty(str(v))

    @field_validator("unit_cost", mode="before")
    @classmethod
    def _coerce_money(cls, v: object) -> Decimal:
        from app.core.money import money

        return money(str(v))


class POLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    po_id: uuid.UUID
    item_id: uuid.UUID | None = None
    description: str
    qty: Decimal
    unit_cost: Decimal
    line_total: Decimal


# ---------------------------------------------------------------- Purchase Orders


class POCreateRequest(BaseModel):
    supplier_id: uuid.UUID
    currency_code: str = Field(default="AED", min_length=3, max_length=3)
    order_date: date
    expected_date: date | None = None
    lines: list[POLineRequest] = Field(..., min_length=1)
    remarks: str | None = None


class POResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    po_no: str
    supplier_id: uuid.UUID
    currency_code: str
    status: str
    order_date: date
    expected_date: date | None = None
    remarks: str | None = None
    created_at: datetime
    updated_at: datetime
    lines: list[POLineResponse] = []


# ------------------------------------------------------------------- GRN Lines


class GRNLineRequest(BaseModel):
    """A single line item in a create GRN request."""

    item_id: uuid.UUID | None = None
    serial_no: str | None = Field(default=None, max_length=100)
    imei: str | None = Field(default=None, max_length=20)
    qty_received: Decimal = Field(..., ge=0)
    unit_cost: Decimal = Field(..., ge=0)

    @field_validator("qty_received", mode="before")
    @classmethod
    def _coerce_qty(cls, v: object) -> Decimal:
        from app.core.money import qty as quantize_qty

        return quantize_qty(str(v))

    @field_validator("unit_cost", mode="before")
    @classmethod
    def _coerce_money(cls, v: object) -> Decimal:
        from app.core.money import money

        return money(str(v))


class GRNLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    grn_id: uuid.UUID
    item_id: uuid.UUID | None = None
    serial_no: str | None = None
    imei: str | None = None
    qty_received: Decimal
    unit_cost: Decimal
    line_total: Decimal


# ------------------------------------------------------------- Goods Receipt Notes


class GRNCreateRequest(BaseModel):
    po_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID
    receipt_date: date
    lines: list[GRNLineRequest] = Field(..., min_length=1)


class GRNResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    grn_no: str
    po_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID
    receipt_date: date
    status: str
    je_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    lines: list[GRNLineResponse] = []
