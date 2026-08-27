"""Procurement models — erp_inv schema.

PurchaseOrder, PurchaseOrderLine, GoodsReceiptNote, GRNLine.
All monetary columns are NUMERIC(19,4).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.procurement.constants import GRNStatus, POStatus

if TYPE_CHECKING:
    pass

_INV = "erp_inv"


class PurchaseOrder(UUIDPKMixin, TimestampMixin, Base):
    """Purchase order — header."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        enum_check("status", POStatus, "ck_purchase_orders_status"),
        UniqueConstraint("po_no", name="uq_purchase_orders_po_no"),
        Index("ix_purchase_orders_supplier", "supplier_id"),
        Index("ix_purchase_orders_status", "status"),
    )

    po_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AED"
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=POStatus.DRAFT.value
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        "PurchaseOrderLine", back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(UUIDPKMixin, Base):
    """Single line item on a purchase order."""

    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        Index("ix_purchase_order_lines_po", "po_id"),
    )

    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    qty: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )

    purchase_order: Mapped["PurchaseOrder"] = relationship(
        "PurchaseOrder", back_populates="lines"
    )


class GoodsReceiptNote(UUIDPKMixin, TimestampMixin, Base):
    """Goods receipt note — header."""

    __tablename__ = "goods_receipt_notes"
    __table_args__ = (
        enum_check("status", GRNStatus, "ck_goods_receipt_notes_status"),
        UniqueConstraint("grn_no", name="uq_goods_receipt_notes_grn_no"),
        Index("ix_goods_receipt_notes_po", "po_id"),
        Index("ix_goods_receipt_notes_warehouse", "warehouse_id"),
    )

    grn_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=GRNStatus.DRAFT.value
    )
    je_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )

    lines: Mapped[list["GRNLine"]] = relationship(
        "GRNLine", back_populates="grn", cascade="all, delete-orphan"
    )


class GRNLine(UUIDPKMixin, Base):
    """Single line item on a goods receipt note."""

    __tablename__ = "grn_lines"
    __table_args__ = (
        Index("ix_grn_lines_grn", "grn_id"),
        Index("ix_grn_lines_serial_no", "serial_no"),
    )

    grn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goods_receipt_notes.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
    )
    serial_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    imei: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qty_received: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )

    grn: Mapped["GoodsReceiptNote"] = relationship(
        "GoodsReceiptNote", back_populates="lines"
    )
