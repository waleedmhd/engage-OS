"""Payables models — erp_fin schema.

SupplierBill, SupplierBillLine, SupplierPayment, BillAllocation, DebitNote.
All monetary columns are NUMERIC(19,4) per the Money value-object contract.
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
from app.modules.payables.constants import (
    BillStatus,
    DebitNoteReason,
    DebitNoteStatus,
    PaymentMethod,
    PaymentStatus,
)

if TYPE_CHECKING:
    from app.modules.contacts.models import Contact
    from app.modules.ledger.models import JournalEntry, TaxCode

# Schema prefix for all tables in this module.
_FIN = "erp_fin"


# ---------------------------------------------------------------- supplier bills


class SupplierBill(UUIDPKMixin, TimestampMixin, Base):
    """Supplier bill (AP invoice) — mirrors receivables SalesInvoice for payables."""

    __tablename__ = "supplier_bills"
    __table_args__ = (
        enum_check("status", BillStatus, "ck_supplier_bills_status"),
        UniqueConstraint("bill_no", name="uq_supplier_bills_bill_no"),
        Index("ix_supplier_bills_supplier", "supplier_id"),
        Index("ix_supplier_bills_status", "status"),
        Index("ix_supplier_bills_due_date", "due_date"),
        Index("ix_supplier_bills_supplier_status", "supplier_id", "status"),
    )

    bill_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="Procurement module may not exist yet"
    )
    grn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="Procurement module may not exist yet"
    )
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("currencies.code", ondelete="RESTRICT"),
        nullable=False,
        default="AED",
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
        String(20), nullable=False, default=BillStatus.DRAFT.value
    )
    je_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    supplier: Mapped["Contact"] = relationship("Contact")
    # Eager for the same reason as SalesInvoice.lines: BillResponse serialises
    # `lines`, and a lazy load during Pydantic extraction under an AsyncSession
    # raises MissingGreenlet.
    lines: Mapped[list["SupplierBillLine"]] = relationship(
        "SupplierBillLine", back_populates="bill", cascade="all, delete-orphan",
        lazy="selectin",
    )
    journal_entry: Mapped["JournalEntry | None"] = relationship(
        "JournalEntry", foreign_keys=[je_id]
    )
    allocations: Mapped[list["BillAllocation"]] = relationship(
        "BillAllocation", back_populates="bill"
    )


class SupplierBillLine(UUIDPKMixin, Base):
    """Line item on a supplier bill."""

    __tablename__ = "supplier_bill_lines"
    __table_args__ = (
        Index("ix_supplier_bill_lines_bill", "bill_id"),
    )

    bill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_bills.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="erp_inv.items may not exist yet"
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    qty: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("1")
    )
    unit_cost: Mapped[Decimal] = mapped_column(
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

    bill: Mapped["SupplierBill"] = relationship("SupplierBill", back_populates="lines")
    tax_code: Mapped["TaxCode | None"] = relationship("TaxCode")


# ---------------------------------------------------------------- payments


class SupplierPayment(UUIDPKMixin, TimestampMixin, Base):
    """Payment made to a supplier."""

    __tablename__ = "supplier_payments"
    __table_args__ = (
        enum_check("payment_method", PaymentMethod, "ck_supplier_payments_method"),
        enum_check("status", PaymentStatus, "ck_supplier_payments_status"),
        UniqueConstraint("payment_no", name="uq_supplier_payments_payment_no"),
        Index("ix_supplier_payments_supplier", "supplier_id"),
        Index("ix_supplier_payments_date", "payment_date"),
    )

    payment_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("currencies.code", ondelete="RESTRICT"),
        nullable=False,
        default="AED",
    )
    fx_rate: Mapped[Decimal] = mapped_column(
        Numeric(19, 8), nullable=False, default=Decimal("1")
    )
    payment_method: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentMethod.BANK_TRANSFER.value
    )
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    je_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.UNCLEARED.value
    )

    supplier: Mapped["Contact"] = relationship("Contact")
    journal_entry: Mapped["JournalEntry | None"] = relationship(
        "JournalEntry", foreign_keys=[je_id]
    )
    allocations: Mapped[list["BillAllocation"]] = relationship(
        "BillAllocation", back_populates="payment", cascade="all, delete-orphan"
    )


class BillAllocation(UUIDPKMixin, Base):
    """Links a payment to a bill — partial or full allocation."""

    __tablename__ = "bill_allocations"
    __table_args__ = (
        UniqueConstraint("payment_id", "bill_id", name="uq_bill_allocations_payment_bill"),
        Index("ix_bill_allocations_payment", "payment_id"),
        Index("ix_bill_allocations_bill", "bill_id"),
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_payments.id", ondelete="CASCADE"),
        nullable=False,
    )
    bill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_bills.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)

    payment: Mapped["SupplierPayment"] = relationship(
        "SupplierPayment", back_populates="allocations"
    )
    bill: Mapped["SupplierBill"] = relationship(
        "SupplierBill", back_populates="allocations"
    )


# ---------------------------------------------------------------- debit notes


class DebitNote(UUIDPKMixin, TimestampMixin, Base):
    """Debit note issued to a supplier (credit from AP perspective — reduces payable)."""

    __tablename__ = "debit_notes"
    __table_args__ = (
        enum_check("reason", DebitNoteReason, "ck_debit_notes_reason"),
        enum_check("status", DebitNoteStatus, "ck_debit_notes_status"),
        UniqueConstraint("debit_note_no", name="uq_debit_notes_debit_note_no"),
        Index("ix_debit_notes_supplier", "supplier_id"),
        Index("ix_debit_notes_bill", "bill_id"),
    )

    debit_note_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    bill_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_bills.id", ondelete="SET NULL"),
        nullable=True,
        comment="Linked to original bill if applicable",
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    reason: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DebitNoteReason.OTHER.value
    )
    currency_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("currencies.code", ondelete="RESTRICT"),
        nullable=False,
        default="AED",
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
        String(20), nullable=False, default=DebitNoteStatus.DRAFT.value
    )

    supplier: Mapped["Contact"] = relationship("Contact")
    bill: Mapped["SupplierBill | None"] = relationship(
        "SupplierBill", foreign_keys=[bill_id]
    )
    journal_entry: Mapped["JournalEntry | None"] = relationship(
        "JournalEntry", foreign_keys=[je_id]
    )
