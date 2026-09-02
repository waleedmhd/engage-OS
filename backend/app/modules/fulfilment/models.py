"""Fulfilment models — erp_inv schema.

SalesOrder, SalesOrderLine, Dispatch, DispatchLine.
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
from app.modules.fulfilment.constants import DispatchStatus, SOStatus

if TYPE_CHECKING:
    pass

_INV = "erp_inv"


class SalesOrder(UUIDPKMixin, TimestampMixin, Base):
    """Sales order — header."""

    __tablename__ = "sales_orders"
    __table_args__ = (
        enum_check("status", SOStatus, "ck_sales_orders_status"),
        UniqueConstraint("so_no", name="uq_sales_orders_so_no"),
        Index("ix_sales_orders_customer", "customer_id"),
        Index("ix_sales_orders_status", "status"),
    )

    so_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AED"
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=SOStatus.DRAFT.value
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)

    lines: Mapped[list["SalesOrderLine"]] = relationship(
        "SalesOrderLine", back_populates="sales_order", cascade="all, delete-orphan",
        lazy="selectin"
    )


class SalesOrderLine(UUIDPKMixin, Base):
    """Single line item on a sales order."""

    __tablename__ = "sales_order_lines"
    __table_args__ = (
        Index("ix_sales_order_lines_so", "so_id"),
    )

    so_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_orders.id", ondelete="CASCADE"),
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
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )

    sales_order: Mapped["SalesOrder"] = relationship(
        "SalesOrder", back_populates="lines"
    )


class Dispatch(UUIDPKMixin, TimestampMixin, Base):
    """Goods dispatch — header."""

    __tablename__ = "dispatches"
    __table_args__ = (
        enum_check("status", DispatchStatus, "ck_dispatches_status"),
        UniqueConstraint("dispatch_no", name="uq_dispatches_dispatch_no"),
        Index("ix_dispatches_so", "so_id"),
    )

    dispatch_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    so_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    dispatch_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=DispatchStatus.DRAFT.value
    )
    je_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )

    lines: Mapped[list["DispatchLine"]] = relationship(
        "DispatchLine", back_populates="dispatch", cascade="all, delete-orphan",
        lazy="selectin"
    )


class DispatchLine(UUIDPKMixin, Base):
    """Single line item on a dispatch."""

    __tablename__ = "dispatch_lines"
    __table_args__ = (
        Index("ix_dispatch_lines_dispatch", "dispatch_id"),
    )

    dispatch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dispatches.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stock_units.id", ondelete="SET NULL"),
        nullable=True,
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
    )
    qty: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )

    dispatch: Mapped["Dispatch"] = relationship(
        "Dispatch", back_populates="lines"
    )
