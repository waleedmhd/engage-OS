"""Ledger models — erp_fin schema.

Account, FiscalPeriod, JournalEntry, JournalLine, TaxCode.
All monetary columns are NUMERIC(19,4) per the Money value-object contract.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from app.modules.ledger.constants import (
    AccountNormalSide,
    AccountType,
    JournalStatus,
    JournalVoucherType,
    PeriodStatus,
)

if TYPE_CHECKING:
    pass

# Schema prefix for all tables in this module.
_FIN = "erp_fin"


class Account(UUIDPKMixin, TimestampMixin, Base):
    """Chart of Accounts — hierarchical tree of GL accounts."""

    __tablename__ = "accounts"
    __table_args__ = (
        enum_check("type", AccountType, "ck_accounts_type"),
        enum_check("normal_side", AccountNormalSide, "ck_accounts_normal_side"),
        UniqueConstraint("code", name="uq_accounts_code"),
        Index("ix_accounts_parent", "parent_id"),
        Index("ix_accounts_type_active", "type", "is_active"),
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    normal_side: Mapped[str] = mapped_column(
        String(10), nullable=False, default=AccountNormalSide.DEBIT.value
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_postable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    parent: Mapped["Account | None"] = relationship(
        "Account", remote_side="Account.id", back_populates="children"
    )
    children: Mapped[list["Account"]] = relationship(
        "Account", back_populates="parent"
    )


class FiscalPeriod(UUIDPKMixin, Base):
    """Monthly accounting period within a fiscal year."""

    __tablename__ = "fiscal_periods"
    __table_args__ = (
        enum_check("status", PeriodStatus, "ck_fiscal_periods_status"),
        UniqueConstraint("fiscal_year", "month", name="uq_fiscal_periods_year_month"),
        Index("ix_fiscal_periods_status", "status"),
    )

    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=PeriodStatus.OPEN.value
    )


class JournalEntry(UUIDPKMixin, TimestampMixin, Base):
    """Double-entry journal header."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        enum_check("status", JournalStatus, "ck_journal_entries_status"),
        enum_check("voucher_type", JournalVoucherType, "ck_journal_entries_voucher_type"),
        Index("ix_journal_entries_date", "posting_date"),
        Index("ix_journal_entries_period", "period_id"),
        Index("ix_journal_entries_source", "source_type", "source_id"),
        Index("ix_journal_entries_status", "status"),
    )

    entry_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fiscal_periods.id", ondelete="RESTRICT"),
        nullable=False,
    )
    voucher_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=JournalVoucherType.JOURNAL_ENTRY.value
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="sales_invoice, grn, dispatch, etc."
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JournalStatus.DRAFT.value
    )
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reversed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    cheque_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cheque_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    clearance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_opening: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_system_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Eager for the same reason as SalesInvoice.lines: JournalEntryResponse
    # serialises `lines`, and a lazy load during Pydantic extraction under an
    # AsyncSession raises MissingGreenlet. get_with_lines()'s explicit
    # joinedload still overrides this per query.
    lines: Mapped[list["JournalLine"]] = relationship(
        "JournalLine", back_populates="entry", cascade="all, delete-orphan",
        lazy="selectin",
    )
    period: Mapped["FiscalPeriod"] = relationship("FiscalPeriod")
    reversed_by: Mapped["JournalEntry | None"] = relationship(
        "JournalEntry", remote_side="JournalEntry.id", foreign_keys=[reversed_by_id]
    )


class JournalLine(UUIDPKMixin, Base):
    """Single debit/credit line within a journal entry.

    Each line is in one account and carries transaction-currency AND base-currency
    (AED) amounts. The invariant Σdr_base = Σcr_base per entry is enforced by the
    PostingService before commit.
    """

    __tablename__ = "journal_lines"
    __table_args__ = (
        Index("ix_journal_lines_entry", "entry_id"),
        Index("ix_journal_lines_account", "account_id"),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Transaction-currency amounts.
    dr: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    cr: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(19, 8), nullable=True)

    # Base-currency amounts (AED).
    dr_base: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )
    cr_base: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, default=Decimal("0")
    )

    # Polymorphic party reference.
    party_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    party_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    entry: Mapped["JournalEntry"] = relationship("JournalEntry", back_populates="lines")
    account: Mapped["Account"] = relationship("Account")


class TaxCode(UUIDPKMixin, Base):
    """Tax code — VAT hook stub. No logic yet; schema only."""

    __tablename__ = "tax_codes"
    __table_args__ = (
        UniqueConstraint("code", name="uq_tax_codes_code"),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), nullable=False, default=Decimal("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Currency(Base):
    """Currency registry — base currency is AED."""

    __tablename__ = "currencies"
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(5), nullable=False)
    is_base: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Uom(Base):
    """Unit of measure."""

    __tablename__ = "uoms"
    __table_args__ = (
        UniqueConstraint("code", name="uq_uoms_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class NumberSequence(Base):
    """Gapless document numbering — per doc_type + fiscal_year."""

    __tablename__ = "number_sequences"
    doc_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_value: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
