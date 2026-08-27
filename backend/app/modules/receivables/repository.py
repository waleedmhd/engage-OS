"""Receivables repositories — sales invoices, payments, allocations, credit notes."""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import BaseRepository
from app.modules.receivables.constants import InvoiceStatus
from app.modules.receivables.models import (
    CreditNote,
    CustomerPayment,
    PaymentAllocation,
    SalesInvoice,
    SalesInvoiceLine,
)


class SalesInvoiceRepository(BaseRepository[SalesInvoice]):
    model = SalesInvoice

    async def get_by_invoice_no(self, invoice_no: str) -> SalesInvoice | None:
        result = await self.session.execute(
            sa.select(SalesInvoice).where(SalesInvoice.invoice_no == invoice_no)
        )
        return result.scalar_one_or_none()

    async def get_with_lines(self, invoice_id: uuid.UUID) -> SalesInvoice | None:
        from sqlalchemy.orm import joinedload

        result = await self.session.execute(
            sa.select(SalesInvoice)
            .options(
                joinedload(SalesInvoice.lines),
            )
            .where(SalesInvoice.id == invoice_id)
        )
        return result.unique().scalar_one_or_none()

    async def list_by_customer(
        self,
        customer_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SalesInvoice]:
        result = await self.session.execute(
            sa.select(SalesInvoice)
            .where(SalesInvoice.customer_id == customer_id)
            .order_by(SalesInvoice.posting_date.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_outstanding(
        self,
        *,
        customer_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SalesInvoice]:
        stmt = (
            sa.select(SalesInvoice)
            .where(SalesInvoice.status.in_([
                InvoiceStatus.ISSUED.value,
                InvoiceStatus.OVERDUE.value,
            ]))
            .order_by(SalesInvoice.due_date.asc())
            .limit(limit)
            .offset(offset)
        )
        if customer_id is not None:
            stmt = stmt.where(SalesInvoice.customer_id == customer_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sum_outstanding(self, customer_id: uuid.UUID | None = None) -> Decimal:
        stmt = sa.select(
            sa.func.coalesce(sa.func.sum(SalesInvoice.total), 0)
        ).where(
            SalesInvoice.status.in_([
                InvoiceStatus.ISSUED.value,
                InvoiceStatus.OVERDUE.value,
            ])
        )
        if customer_id is not None:
            stmt = stmt.where(SalesInvoice.customer_id == customer_id)
        result = await self.session.execute(stmt)
        return Decimal(str(result.scalar_one()))

    async def list_paginated(
        self,
        *,
        customer_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SalesInvoice]:
        stmt = sa.select(SalesInvoice).order_by(SalesInvoice.posting_date.desc())
        if customer_id is not None:
            stmt = stmt.where(SalesInvoice.customer_id == customer_id)
        if status is not None:
            from enum import Enum

            if isinstance(status, Enum):
                status = status.value
            stmt = stmt.where(SalesInvoice.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_overdue_and_issued(self) -> list[SalesInvoice]:
        """Return invoices that are issued but past their due date — for the ageing task."""
        result = await self.session.execute(
            sa.select(SalesInvoice).where(
                SalesInvoice.status == InvoiceStatus.ISSUED.value,
                SalesInvoice.due_date < sa.func.current_date(),
            )
        )
        return list(result.scalars().all())

    async def generate_invoice_no(self) -> str:
        """Generate the next invoice number: INV-YYYY-00001 style."""
        year = sa.func.extract("year", sa.func.now())
        # Count existing invoices this year + 1, padded to 5 digits.
        count_stmt = sa.select(sa.func.count()).where(
            sa.func.extract("year", SalesInvoice.created_at) == year
        )
        result = await self.session.execute(count_stmt)
        count = result.scalar_one() + 1
        return f"INV-{int(year)}-{count:05d}"


class SalesInvoiceLineRepository(BaseRepository[SalesInvoiceLine]):
    model = SalesInvoiceLine

    async def list_by_invoice(self, invoice_id: uuid.UUID) -> list[SalesInvoiceLine]:
        result = await self.session.execute(
            sa.select(SalesInvoiceLine).where(
                SalesInvoiceLine.invoice_id == invoice_id
            )
        )
        return list(result.scalars().all())


class CustomerPaymentRepository(BaseRepository[CustomerPayment]):
    model = CustomerPayment

    async def get_by_payment_no(self, payment_no: str) -> CustomerPayment | None:
        result = await self.session.execute(
            sa.select(CustomerPayment).where(CustomerPayment.payment_no == payment_no)
        )
        return result.scalar_one_or_none()

    async def list_by_customer(
        self,
        customer_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CustomerPayment]:
        result = await self.session.execute(
            sa.select(CustomerPayment)
            .where(CustomerPayment.customer_id == customer_id)
            .order_by(CustomerPayment.payment_date.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def generate_payment_no(self) -> str:
        """Generate the next payment number: PMT-YYYY-00001 style."""
        year = sa.func.extract("year", sa.func.now())
        count_stmt = sa.select(sa.func.count()).where(
            sa.func.extract("year", CustomerPayment.created_at) == year
        )
        result = await self.session.execute(count_stmt)
        count = result.scalar_one() + 1
        return f"PMT-{int(year)}-{count:05d}"


class PaymentAllocationRepository(BaseRepository[PaymentAllocation]):
    model = PaymentAllocation

    async def get_for_invoice(self, invoice_id: uuid.UUID) -> list[PaymentAllocation]:
        result = await self.session.execute(
            sa.select(PaymentAllocation).where(
                PaymentAllocation.invoice_id == invoice_id
            )
        )
        return list(result.scalars().all())

    async def sum_allocated(self, invoice_id: uuid.UUID) -> Decimal:
        result = await self.session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(PaymentAllocation.amount), 0)
            ).where(PaymentAllocation.invoice_id == invoice_id)
        )
        return Decimal(str(result.scalar_one()))

    async def sum_allocated_for_payment(self, payment_id: uuid.UUID) -> Decimal:
        result = await self.session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(PaymentAllocation.amount), 0)
            ).where(PaymentAllocation.payment_id == payment_id)
        )
        return Decimal(str(result.scalar_one()))


class CreditNoteRepository(BaseRepository[CreditNote]):
    model = CreditNote

    async def get_by_credit_note_no(self, credit_note_no: str) -> CreditNote | None:
        result = await self.session.execute(
            sa.select(CreditNote).where(CreditNote.credit_note_no == credit_note_no)
        )
        return result.scalar_one_or_none()

    async def list_by_customer(
        self,
        customer_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CreditNote]:
        result = await self.session.execute(
            sa.select(CreditNote)
            .where(CreditNote.customer_id == customer_id)
            .order_by(CreditNote.date.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def generate_credit_note_no(self) -> str:
        """Generate the next credit note number: CN-YYYY-00001 style."""
        year = sa.func.extract("year", sa.func.now())
        count_stmt = sa.select(sa.func.count()).where(
            sa.func.extract("year", CreditNote.created_at) == year
        )
        result = await self.session.execute(count_stmt)
        count = result.scalar_one() + 1
        return f"CN-{int(year)}-{count:05d}"
