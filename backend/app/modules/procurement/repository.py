"""Procurement repositories — purchase orders and goods receipt notes."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import BaseRepository
from app.modules.procurement.models import (
    GoodsReceiptNote,
    GRNLine,
    PurchaseOrder,
    PurchaseOrderLine,
)


class PurchaseOrderRepository(BaseRepository[PurchaseOrder]):
    model = PurchaseOrder

    async def get_by_po_no(self, po_no: str) -> PurchaseOrder | None:
        result = await self.session.execute(
            sa.select(PurchaseOrder).where(PurchaseOrder.po_no == po_no)
        )
        return result.scalar_one_or_none()

    async def get_with_lines(self, po_id: uuid.UUID) -> PurchaseOrder | None:
        from sqlalchemy.orm import joinedload

        result = await self.session.execute(
            sa.select(PurchaseOrder)
            .options(joinedload(PurchaseOrder.lines))
            .where(PurchaseOrder.id == po_id)
        )
        return result.unique().scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        supplier_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PurchaseOrder]:
        stmt = sa.select(PurchaseOrder).order_by(PurchaseOrder.order_date.desc())
        if supplier_id is not None:
            stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
        if status is not None:
            stmt = stmt.where(PurchaseOrder.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def generate_po_no(self) -> str:
        """Generate the next PO number: PO-YYYY-00001 style."""
        year = sa.func.extract("year", sa.func.now())
        count_stmt = sa.select(sa.func.count()).where(
            sa.func.extract("year", PurchaseOrder.created_at) == year
        )
        result = await self.session.execute(count_stmt)
        count = result.scalar_one() + 1
        return f"PO-{int(year)}-{count:05d}"


class PurchaseOrderLineRepository(BaseRepository[PurchaseOrderLine]):
    model = PurchaseOrderLine

    async def list_by_po(self, po_id: uuid.UUID) -> list[PurchaseOrderLine]:
        result = await self.session.execute(
            sa.select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)
        )
        return list(result.scalars().all())


class GRNRepository(BaseRepository[GoodsReceiptNote]):
    model = GoodsReceiptNote

    async def get_by_grn_no(self, grn_no: str) -> GoodsReceiptNote | None:
        result = await self.session.execute(
            sa.select(GoodsReceiptNote).where(GoodsReceiptNote.grn_no == grn_no)
        )
        return result.scalar_one_or_none()

    async def get_with_lines(self, grn_id: uuid.UUID) -> GoodsReceiptNote | None:
        from sqlalchemy.orm import joinedload

        result = await self.session.execute(
            sa.select(GoodsReceiptNote)
            .options(joinedload(GoodsReceiptNote.lines))
            .where(GoodsReceiptNote.id == grn_id)
        )
        return result.unique().scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        po_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GoodsReceiptNote]:
        stmt = sa.select(GoodsReceiptNote).order_by(GoodsReceiptNote.receipt_date.desc())
        if po_id is not None:
            stmt = stmt.where(GoodsReceiptNote.po_id == po_id)
        if warehouse_id is not None:
            stmt = stmt.where(GoodsReceiptNote.warehouse_id == warehouse_id)
        if status is not None:
            stmt = stmt.where(GoodsReceiptNote.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def generate_grn_no(self) -> str:
        """Generate the next GRN number: GRN-YYYY-00001 style."""
        year = sa.func.extract("year", sa.func.now())
        count_stmt = sa.select(sa.func.count()).where(
            sa.func.extract("year", GoodsReceiptNote.created_at) == year
        )
        result = await self.session.execute(count_stmt)
        count = result.scalar_one() + 1
        return f"GRN-{int(year)}-{count:05d}"


class GRNLineRepository(BaseRepository[GRNLine]):
    model = GRNLine

    async def list_by_grn(self, grn_id: uuid.UUID) -> list[GRNLine]:
        result = await self.session.execute(
            sa.select(GRNLine).where(GRNLine.grn_id == grn_id)
        )
        return list(result.scalars().all())
