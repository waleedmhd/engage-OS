"""Payables repositories — bills, payments, allocations, debit notes."""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from app.db.repository import BaseRepository
from app.modules.payables.constants import BillStatus
from app.modules.payables.models import (
    BillAllocation,
    DebitNote,
    SupplierBill,
    SupplierBillLine,
    SupplierPayment,
)


class SupplierBillRepository(BaseRepository[SupplierBill]):
    model = SupplierBill

    async def get_by_bill_no(self, bill_no: str) -> SupplierBill | None:
        result = await self.session.execute(
            sa.select(SupplierBill).where(SupplierBill.bill_no == bill_no)
        )
        return result.scalar_one_or_none()

    async def get_with_lines(self, bill_id: uuid.UUID) -> SupplierBill | None:
        result = await self.session.execute(
            sa.select(SupplierBill)
            .options(joinedload(SupplierBill.lines))
            .where(SupplierBill.id == bill_id)
        )
        return result.unique().scalar_one_or_none()

    async def list_by_supplier(
        self,
        supplier_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SupplierBill]:
        stmt = (
            sa.select(SupplierBill)
            .where(SupplierBill.supplier_id == supplier_id)
            .order_by(SupplierBill.due_date.desc())
        )
        if status is not None:
            stmt = stmt.where(SupplierBill.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_outstanding(
        self,
        *,
        supplier_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SupplierBill]:
        """Return issued bills that have not been fully allocated/paid."""
        stmt = (
            sa.select(SupplierBill)
            .where(
                SupplierBill.status.in_(
                    [BillStatus.ISSUED.value, BillStatus.OVERDUE.value]
                )
            )
            .order_by(SupplierBill.due_date.asc())
        )
        if supplier_id is not None:
            stmt = stmt.where(SupplierBill.supplier_id == supplier_id)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_supplier(self, supplier_id: uuid.UUID) -> int:
        result = await self.session.execute(
            sa.select(sa.func.count()).where(
                SupplierBill.supplier_id == supplier_id
            )
        )
        return result.scalar_one()


class SupplierBillLineRepository(BaseRepository[SupplierBillLine]):
    model = SupplierBillLine

    async def list_by_bill(self, bill_id: uuid.UUID) -> list[SupplierBillLine]:
        result = await self.session.execute(
            sa.select(SupplierBillLine)
            .where(SupplierBillLine.bill_id == bill_id)
            .order_by(SupplierBillLine.id)
        )
        return list(result.scalars().all())


class SupplierPaymentRepository(BaseRepository[SupplierPayment]):
    model = SupplierPayment

    async def get_by_payment_no(self, payment_no: str) -> SupplierPayment | None:
        result = await self.session.execute(
            sa.select(SupplierPayment).where(SupplierPayment.payment_no == payment_no)
        )
        return result.scalar_one_or_none()

    async def list_by_supplier(
        self,
        supplier_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SupplierPayment]:
        stmt = (
            sa.select(SupplierPayment)
            .where(SupplierPayment.supplier_id == supplier_id)
            .order_by(SupplierPayment.payment_date.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_allocations(self, payment_id: uuid.UUID) -> SupplierPayment | None:
        result = await self.session.execute(
            sa.select(SupplierPayment)
            .options(joinedload(SupplierPayment.allocations))
            .where(SupplierPayment.id == payment_id)
        )
        return result.unique().scalar_one_or_none()


class BillAllocationRepository(BaseRepository[BillAllocation]):
    model = BillAllocation

    async def get_for_bill(self, bill_id: uuid.UUID) -> list[BillAllocation]:
        result = await self.session.execute(
            sa.select(BillAllocation).where(BillAllocation.bill_id == bill_id)
        )
        return list(result.scalars().all())

    async def sum_allocated(self, bill_id: uuid.UUID) -> Decimal:
        result = await self.session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(BillAllocation.amount), 0)
            ).where(BillAllocation.bill_id == bill_id)
        )
        return Decimal(str(result.scalar_one()))


class DebitNoteRepository(BaseRepository[DebitNote]):
    model = DebitNote

    async def get_by_debit_note_no(self, debit_note_no: str) -> DebitNote | None:
        result = await self.session.execute(
            sa.select(DebitNote).where(DebitNote.debit_note_no == debit_note_no)
        )
        return result.scalar_one_or_none()

    async def list_by_supplier(
        self,
        supplier_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DebitNote]:
        stmt = (
            sa.select(DebitNote)
            .where(DebitNote.supplier_id == supplier_id)
            .order_by(DebitNote.date.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
