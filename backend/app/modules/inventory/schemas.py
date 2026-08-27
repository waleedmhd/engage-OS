"""Inventory request/response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.inventory.constants import (
    AdjustmentReason,
    ItemNature,
    ValuationMethod,
)


# ----------------------------------------------------------------------- Items


class ItemCreateRequest(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    nature: str = Field(default=ItemNature.BULK.value)
    uom_id: uuid.UUID
    valuation_method: str = Field(default=ValuationMethod.MOVING_AVG.value)
    reorder_level: int = Field(default=0, ge=0)
    reorder_qty: Decimal = Field(default=Decimal("0"), ge=0)
    default_purchase_price: Decimal = Field(default=Decimal("0"), ge=0)
    default_sale_price: Decimal = Field(default=Decimal("0"), ge=0)
    inventory_account_id: uuid.UUID
    cogs_account_id: uuid.UUID
    revenue_account_id: uuid.UUID
    is_sales_item: bool = True
    is_purchase_item: bool = True
    end_of_life: date | None = None
    lead_time_days: int | None = None
    safety_stock: Decimal | None = None
    weight_per_unit: Decimal | None = None
    weight_uom_id: uuid.UUID | None = None
    country_of_origin: str | None = Field(default=None, min_length=2, max_length=2)
    customs_tariff_number: str | None = Field(default=None, max_length=20)
    description: str | None = None

    @field_validator("nature")
    @classmethod
    def _check_nature(cls, v: str) -> str:
        valid = {e.value for e in ItemNature}
        if v not in valid:
            raise ValueError(f"nature must be one of {sorted(valid)}")
        return v

    @field_validator("valuation_method")
    @classmethod
    def _check_valuation_method(cls, v: str) -> str:
        valid = {e.value for e in ValuationMethod}
        if v not in valid:
            raise ValueError(f"valuation_method must be one of {sorted(valid)}")
        return v

    @field_validator(
        "default_purchase_price",
        "default_sale_price",
        "reorder_qty",
        mode="before",
    )
    @classmethod
    def _coerce_money(cls, v: object) -> Decimal:
        from app.core.money import money

        return money(str(v))


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    nature: str
    uom_id: uuid.UUID
    valuation_method: str
    reorder_level: int
    reorder_qty: Decimal
    default_purchase_price: Decimal
    default_sale_price: Decimal
    inventory_account_id: uuid.UUID
    cogs_account_id: uuid.UUID
    revenue_account_id: uuid.UUID
    is_sales_item: bool
    is_purchase_item: bool
    is_active: bool
    end_of_life: date | None = None
    lead_time_days: int | None = None
    safety_stock: Decimal | None = None
    weight_per_unit: Decimal | None = None
    weight_uom_id: uuid.UUID | None = None
    country_of_origin: str | None = None
    customs_tariff_number: str | None = None
    description: str | None = None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------- Warehouses


class WarehouseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=20)


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# -------------------------------------------------------------------- Locations


class LocationCreateRequest(BaseModel):
    warehouse_code: str = Field(..., min_length=1, max_length=20)
    code: str = Field(..., min_length=1, max_length=50)


class LocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    warehouse_id: uuid.UUID
    warehouse_code: str
    code: str
    is_active: bool


# ------------------------------------------------------------------- StockUnits


class StockUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    item_name: str = ""
    serial_no: str
    imei: str | None = None
    status: str
    location_id: uuid.UUID | None = None
    location_code: str | None = None
    purchase_cost: Decimal
    grn_id: uuid.UUID | None = None
    sales_dispatch_id: uuid.UUID | None = None
    warranty_expiry_date: date | None = None
    amc_expiry_date: date | None = None
    maintenance_status: str | None = None
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------- Stock On Hand


class StockOnHandResponse(BaseModel):
    item_id: uuid.UUID
    item_name: str
    warehouse_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    location_code: str | None = None
    qty: Decimal
    value: Decimal


# -------------------------------------------------------------- Serial Lookup


class SerialMovement(BaseModel):
    posting_date: date
    voucher_type: str
    voucher_id: uuid.UUID
    qty_change: Decimal
    valuation_rate: Decimal
    status_after: str | None = None


class SerialLookupResponse(BaseModel):
    serial_no: str
    item_id: uuid.UUID | None = None
    item_name: str | None = None
    status: str
    location: str | None = None
    lifecycle: list[SerialMovement] = []


# ------------------------------------------------------------ Stock Ledger Entry


class StockLedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    posting_date: date
    item_id: uuid.UUID
    warehouse_id: uuid.UUID | None = None
    stock_unit_id: uuid.UUID | None = None
    voucher_type: str
    voucher_id: uuid.UUID
    qty_change: Decimal
    valuation_rate: Decimal
    stock_value_change: Decimal
    qty_after: Decimal
    is_cancelled: bool


# -------------------------------------------------------------- Stock Adjustment


class StockAdjustmentRequest(BaseModel):
    item_id: uuid.UUID
    location_id: uuid.UUID
    adjustment_id: uuid.UUID
    qty_adjustment: Decimal
    reason_code: str = Field(default=AdjustmentReason.OTHER.value)
    posting_date: date

    @field_validator("qty_adjustment", mode="before")
    @classmethod
    def _coerce_qty(cls, v: object) -> Decimal:
        from app.core.money import qty

        return qty(str(v))

    @field_validator("reason_code")
    @classmethod
    def _check_reason(cls, v: str) -> str:
        valid = {e.value for e in AdjustmentReason}
        if v not in valid:
            raise ValueError(f"reason_code must be one of {sorted(valid)}")
        return v


class StockAdjustmentResponse(BaseModel):
    adjustment_id: uuid.UUID
    sle_id: uuid.UUID
    item_id: uuid.UUID
    location_id: uuid.UUID
    qty_adjustment: Decimal
    qty_after: Decimal
    amount: Decimal
    posting_date: date


# --------------------------------------------------------------- Stock Transfer


class StockTransferRequest(BaseModel):
    stock_unit_ids: list[uuid.UUID] = Field(..., min_length=1)
    to_location_id: uuid.UUID
    transfer_id: uuid.UUID
    posting_date: date


# ------------------------------------------------------------- Stock Valuation


class StockValuationResponse(BaseModel):
    total_value: Decimal
    item_count: int
    last_reconciled_at: datetime | None = None


class StockReconciliationResponse(BaseModel):
    stock_value: Decimal
    gl_balance: Decimal
    variance: Decimal
    reconciled: bool
