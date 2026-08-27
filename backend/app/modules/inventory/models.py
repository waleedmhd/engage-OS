"""Inventory models — erp_inv schema.

Item, Warehouse, Location, StockUnit, StockBalance, StockLedgerEntry.
SerialNo lives in the crm schema (Path C design — serial registry at CRM level).

All monetary columns are NUMERIC(19,4); quantity columns are NUMERIC(12,2).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.inventory.constants import (
    ItemNature,
    StockUnitStatus,
    StockVoucherType,
    ValuationMethod,
)

if TYPE_CHECKING:
    pass

_INV = "erp_inv"


# --------------------------------------------------------------------- Item


class Item(UUIDPKMixin, TimestampMixin, Base):
    """Inventory item master — finished goods, raw materials, consumables."""

    __tablename__ = "items"
    __table_args__ = (
        enum_check("nature", ItemNature, "ck_items_nature"),
        enum_check("valuation_method", ValuationMethod, "ck_items_valuation_method"),
        UniqueConstraint("sku", name="uq_items_sku"),
        Index("ix_items_category", "category"),
        Index("ix_items_nature", "nature"),
    )

    sku: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nature: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ItemNature.BULK.value
    )
    uom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("uoms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    valuation_method: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ValuationMethod.MOVING_AVG.value
    )
    reorder_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reorder_qty: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    default_purchase_price: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    default_sale_price: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    inventory_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    cogs_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revenue_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_sales_item: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_purchase_item: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    end_of_life: Mapped[date | None] = mapped_column(Date, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safety_stock: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    weight_per_unit: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3), nullable=True
    )
    weight_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("uoms.id", ondelete="SET NULL"),
        nullable=True,
    )
    country_of_origin: Mapped[str | None] = mapped_column(String(2), nullable=True)
    customs_tariff_number: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    stock_units: Mapped[list["StockUnit"]] = relationship(
        "StockUnit", back_populates="item"
    )
    stock_balances: Mapped[list["StockBalance"]] = relationship(
        "StockBalance", back_populates="item"
    )
    ledger_entries: Mapped[list["StockLedgerEntry"]] = relationship(
        "StockLedgerEntry", back_populates="item"
    )


# ------------------------------------------------------------------ Warehouse


class Warehouse(UUIDPKMixin, TimestampMixin, Base):
    """Physical or logical warehouse / storage facility."""

    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("code", name="uq_warehouses_code"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    locations: Mapped[list["Location"]] = relationship(
        "Location", back_populates="warehouse"
    )
    stock_ledger_entries: Mapped[list["StockLedgerEntry"]] = relationship(
        "StockLedgerEntry", back_populates="warehouse"
    )


# -------------------------------------------------------------------- Location


class Location(UUIDPKMixin, Base):
    """Bin / shelf / zone within a warehouse."""

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "code", name="uq_locations_warehouse_code"),
    )

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    warehouse: Mapped["Warehouse"] = relationship(
        "Warehouse", back_populates="locations"
    )
    stock_units: Mapped[list["StockUnit"]] = relationship(
        "StockUnit", back_populates="location"
    )
    stock_balances: Mapped[list["StockBalance"]] = relationship(
        "StockBalance", back_populates="location"
    )


# ------------------------------------------------------------------- StockUnit


class StockUnit(UUIDPKMixin, TimestampMixin, Base):
    """A single serialized unit (phone, laptop, appliance)."""

    __tablename__ = "stock_units"
    __table_args__ = (
        enum_check("status", StockUnitStatus, "ck_stock_units_status"),
        UniqueConstraint("serial_no", name="uq_stock_units_serial_no"),
        Index("ix_stock_units_serial_no", "serial_no"),
        Index("ix_stock_units_status", "status"),
        Index("ix_stock_units_item", "item_id"),
        Index("ix_stock_units_location", "location_id"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    serial_no: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    imei: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StockUnitStatus.IN_STOCK.value
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    purchase_cost: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    grn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="Procurement GRN reference — no FK"
    )
    sales_dispatch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Fulfilment dispatch reference — no FK",
    )
    warranty_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amc_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    maintenance_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )

    item: Mapped["Item"] = relationship("Item", back_populates="stock_units")
    location: Mapped["Location | None"] = relationship(
        "Location", back_populates="stock_units"
    )
    ledger_entries: Mapped[list["StockLedgerEntry"]] = relationship(
        "StockLedgerEntry", back_populates="stock_unit"
    )


# ----------------------------------------------------------------- StockBalance


class StockBalance(UUIDPKMixin, Base):
    """Materialized quantity-on-hand and average cost per item+location."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint(
            "item_id", "location_id", name="uq_stock_balances_item_location"
        ),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
    )
    qty: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    avg_cost: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )

    item: Mapped["Item"] = relationship("Item", back_populates="stock_balances")
    location: Mapped["Location"] = relationship(
        "Location", back_populates="stock_balances"
    )


# ------------------------------------------------------------ StockLedgerEntry


class StockLedgerEntry(UUIDPKMixin, Base):
    """Immutable ledger of every stock movement — GRN, dispatch, transfer, adjustment."""

    __tablename__ = "stock_ledger_entries"
    __table_args__ = (
        enum_check(
            "voucher_type", StockVoucherType, "ck_stock_ledger_entries_voucher_type"
        ),
        Index("ix_stock_ledger_entries_item_date", "item_id", "posting_date"),
        Index("ix_stock_ledger_entries_stock_unit", "stock_unit_id"),
        Index("ix_stock_ledger_entries_voucher", "voucher_type", "voucher_id"),
    )

    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="SET NULL"),
        nullable=True,
    )
    stock_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stock_units.id", ondelete="SET NULL"),
        nullable=True,
    )
    voucher_type: Mapped[str] = mapped_column(String(30), nullable=False)
    voucher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    qty_change: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    valuation_rate: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    stock_value_change: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    qty_after: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    is_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    item: Mapped["Item"] = relationship("Item", back_populates="ledger_entries")
    warehouse: Mapped["Warehouse | None"] = relationship(
        "Warehouse", back_populates="stock_ledger_entries"
    )
    stock_unit: Mapped["StockUnit | None"] = relationship(
        "StockUnit", back_populates="ledger_entries"
    )


# -------------------------------------------------------------------- SerialNo
# Path C design: serial registry lives at CRM level (schema = crm).


class SerialNo(UUIDPKMixin, TimestampMixin, Base):
    """Serial number registry — CRM-level, not ERP-inventory.

    Tracks a serial number's lifecycle across the organisation:
    which item it belongs to, current status, which warehouse it is in,
    and the customer it was ultimately delivered to.
    """

    __tablename__ = "serial_nos"
    __table_args__: tuple = (
        UniqueConstraint("serial_no", name="uq_serial_nos_serial_no"),
        Index("ix_serial_nos_status", "status"),
        Index("ix_serial_nos_item", "item_id"),
    )

    serial_no: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="SET NULL"),
        nullable=True,
    )
    purchase_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(19, 4), nullable=True
    )
    warranty_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amc_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    maintenance_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    delivered_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    sale_date: Mapped[date | None] = mapped_column(Date, nullable=True)
