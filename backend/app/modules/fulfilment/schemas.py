"""Fulfilment request/response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ------------------------------------------------------------------- SO Lines


class SOLineRequest(BaseModel):
    """A single line item in a create sales order request."""

    item_id: uuid.UUID | None = None
    description: str = Field(default="", max_length=500)
    qty: Decimal = Field(..., ge=0)
    unit_price: Decimal = Field(..., ge=0)

    @field_validator("qty", mode="before")
    @classmethod
    def _coerce_qty(cls, v: object) -> Decimal:
        from app.core.money import qty as quantize_qty

        return quantize_qty(str(v))

    @field_validator("unit_price", mode="before")
    @classmethod
    def _coerce_money(cls, v: object) -> Decimal:
        from app.core.money import money

        return money(str(v))


class SOLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    so_id: uuid.UUID
    item_id: uuid.UUID | None = None
    description: str
    qty: Decimal
    unit_price: Decimal
    line_total: Decimal


# ------------------------------------------------------------------- Sales Orders


class SOCreateRequest(BaseModel):
    customer_id: uuid.UUID
    currency_code: str = Field(default="AED", min_length=3, max_length=3)
    order_date: date
    lines: list[SOLineRequest] = Field(..., min_length=1)


class SOResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    so_no: str
    customer_id: uuid.UUID
    currency_code: str
    status: str
    order_date: date
    created_at: datetime
    updated_at: datetime
    lines: list[SOLineResponse] = []


# ---------------------------------------------------------------- Dispatch Lines


class DispatchLineRequest(BaseModel):
    """A single line item in a create dispatch request."""

    stock_unit_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    qty: Decimal = Field(default=Decimal("0"), ge=0)
    unit_cost: Decimal | None = None

    @field_validator("qty", mode="before")
    @classmethod
    def _coerce_qty(cls, v: object) -> Decimal:
        from app.core.money import qty as quantize_qty

        return quantize_qty(str(v))

    @field_validator("unit_cost", mode="before")
    @classmethod
    def _coerce_money(cls, v: object) -> Decimal | None:
        if v is None:
            return None
        from app.core.money import money

        return money(str(v))


class DispatchLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dispatch_id: uuid.UUID
    stock_unit_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    qty: Decimal
    unit_cost: Decimal


# --------------------------------------------------------------------- Dispatches


class DispatchCreateRequest(BaseModel):
    so_id: uuid.UUID | None = None
    dispatch_date: date
    lines: list[DispatchLineRequest] = Field(..., min_length=1)


class DispatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dispatch_no: str
    so_id: uuid.UUID | None = None
    dispatch_date: date
    status: str
    je_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    lines: list[DispatchLineResponse] = []
