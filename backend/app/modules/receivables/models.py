"""Receivables (AR) models — erp_fin schema.

SalesInvoice, SalesInvoiceLine, CustomerPayment, PaymentAllocation, CreditNote.
All monetary columns are NUMERIC(19,4) per the Money value-object contract.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
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
from app.modules.receivables.constants import (
    CreditNoteReason,
    CreditNoteStatus,
    InvoiceStatus,
    PaymentMethod,
    PaymentStatus,
)

if TYPE_CHECKING:
    pass

_FIN = "erp_fin"


class SalesInvoice(UUIDPKMixin, TimestampMixin, Base):
    """Customer invoice — header."""

    __tablename__ = "sales_invoices"
    __table_args__ = (
        enum_check("status", InvoiceStatus, "ck_sales_invoices_status"),
        UniqueConstraint("invoice_no", name="uq_sales_invoices_invoice_no"),
        Index("ix_sales_invoices_customer", "customer_id"),
        Index("ix_sales_invoices_status", "status"),
        Index("ix_sales_invoices_due_date", "due_date"),
    )

    invoice_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AED"
    )
    fx_rate: Mapped[Decimal] = mapped_column(
        Numeric(19, 8), nullable=False, default=Decimal("1")
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    tax_total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=InvoiceStatus.DRAFT.value
    )
    je_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list["SalesInvoiceLine"]] = relationship(
        "SalesInvoiceLine", back_populates="invoice", cascade="all, delete-orphan"
    )


class SalesInvoiceLine(UUIDPKMixin, Base):
    """Single line item on a sales invoice."""

    __tablename__ = "sales_invoice_lines"
    __table_args__ = (
        Index("ix_sales_invoice_lines_invoice", "invoice_id"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    # item_id FK omitted intentionally — the erp_inv.items table does not exist yet.
    # Store as a plain UUID column; a proper FK can be added in a later migration.
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
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
    tax_code_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tax_codes.id", ondelete="SET NULL"),
        nullable=True,
    )
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), nullable=False, default=Decimal("0")
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )

    invoice: Mapped["SalesInvoice"] = relationship(
        "SalesInvoice", back_populates="lines"
    )


class CustomerPayment(UUIDPKMixin, TimestampMixin, Base):
    """Payment received from a customer."""

    __tablename__ = "customer_payments"
    __table_args__ = (
        enum_check("status", PaymentStatus, "ck_customer_payments_status"),
        UniqueConstraint("payment_no", name="uq_customer_payments_payment_no"),
        Index("ix_customer_payments_customer", "customer_id"),
        Index("ix_customer_payments_date", "payment_date"),
    )

    payment_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AED"
    )
    fx_rate: Mapped[Decimal] = mapped_column(
        Numeric(19, 8), nullable=False, default=Decimal("1")
    )
    payment_method: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentMethod.BANK_TRANSFER.value
    )
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    je_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=PaymentStatus.UNCLEARED.value
    )

    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        "PaymentAllocation", back_populates="payment", cascade="all, delete-orphan"
    )


class PaymentAllocation(UUIDPKMixin, Base):
    """Links a payment to an invoice — partial or full allocation."""

    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("payment_id", "invoice_id", name="uq_payment_allocations"),
        Index("ix_payment_allocations_invoice", "invoice_id"),
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_payments.id", ondelete="CASCADE"),
        nullable=False,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_invoices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )

    payment: Mapped["CustomerPayment"] = relationship(
        "CustomerPayment", back_populates="allocations"
    )
    invoice: Mapped["SalesInvoice"] = relationship("SalesInvoice")


class CreditNote(UUIDPKMixin, TimestampMixin, Base):
    """Credit note issued to a customer — reduces AR balance."""

    __tablename__ = "credit_notes"
    __table_args__ = (
        enum_check("reason", CreditNoteReason, "ck_credit_notes_reason"),
        enum_check("status", CreditNoteStatus, "ck_credit_notes_status"),
        UniqueConstraint("credit_note_no", name="uq_credit_notes_credit_note_no"),
        Index("ix_credit_notes_customer", "customer_id"),
        Index("ix_credit_notes_invoice", "invoice_id"),
    )

    credit_note_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_invoices.id", ondelete="SET NULL"),
        nullable=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    reason: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CreditNoteReason.OTHER.value
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AED"
    )
    fx_rate: Mapped[Decimal] = mapped_column(
        Numeric(19, 8), nullable=False, default=Decimal("1")
    )
    je_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=CreditNoteStatus.DRAFT.value
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
