"""Fulfilment repositories — sales orders and dispatches."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import BaseRepository
from app.modules.fulfilment.models import (
    Dispatch,
    DispatchLine,
    SalesOrder,
    SalesOrderLine,
)


class SalesOrderRepository(BaseRepository[SalesOrder]):
    model = SalesOrder

    async def get_by_so_no(self, so_no: str) -> SalesOrder | None:
        result = await self.session.execute(
            sa.select(SalesOrder).where(SalesOrder.so_no == so_no)
        )
        return result.scalar_one_or_none()

    async def get_with_lines(self, so_id: uuid.UUID) -> SalesOrder | None:
        from sqlalchemy.orm import joinedload

        result = await self.session.execute(
            sa.select(SalesOrder)
            .options(joinedload(SalesOrder.lines))
            .where(SalesOrder.id == so_id)
        )
        return result.unique().scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        customer_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SalesOrder]:
        stmt = sa.select(SalesOrder).order_by(SalesOrder.order_date.desc())
        if customer_id is not None:
            stmt = stmt.where(SalesOrder.customer_id == customer_id)
        if status is not None:
            stmt = stmt.where(SalesOrder.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def generate_so_no(self) -> str:
        """Generate the next SO number: SO-YYYY-00001 style."""
        year = sa.func.extract("year", sa.func.now())
        count_stmt = sa.select(sa.func.count()).where(
            sa.func.extract("year", SalesOrder.created_at) == year
        )
        result = await self.session.execute(count_stmt)
        count = result.scalar_one() + 1
        return f"SO-{int(year)}-{count:05d}"


class SalesOrderLineRepository(BaseRepository[SalesOrderLine]):
    model = SalesOrderLine

    async def list_by_so(self, so_id: uuid.UUID) -> list[SalesOrderLine]:
        result = await self.session.execute(
            sa.select(SalesOrderLine).where(SalesOrderLine.so_id == so_id)
        )
        return list(result.scalars().all())


class DispatchRepository(BaseRepository[Dispatch]):
    model = Dispatch

    async def get_by_dispatch_no(self, dispatch_no: str) -> Dispatch | None:
        result = await self.session.execute(
            sa.select(Dispatch).where(Dispatch.dispatch_no == dispatch_no)
        )
        return result.scalar_one_or_none()

    async def get_with_lines(self, dispatch_id: uuid.UUID) -> Dispatch | None:
        from sqlalchemy.orm import joinedload

        result = await self.session.execute(
            sa.select(Dispatch)
            .options(joinedload(Dispatch.lines))
            .where(Dispatch.id == dispatch_id)
        )
        return result.unique().scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        so_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Dispatch]:
        stmt = sa.select(Dispatch).order_by(Dispatch.dispatch_date.desc())
        if so_id is not None:
            stmt = stmt.where(Dispatch.so_id == so_id)
        if status is not None:
            stmt = stmt.where(Dispatch.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def generate_dispatch_no(self) -> str:
        """Generate the next dispatch number: DPN-YYYY-00001 style."""
        year = sa.func.extract("year", sa.func.now())
        count_stmt = sa.select(sa.func.count()).where(
            sa.func.extract("year", Dispatch.created_at) == year
        )
        result = await self.session.execute(count_stmt)
        count = result.scalar_one() + 1
        return f"DPN-{int(year)}-{count:05d}"


class DispatchLineRepository(BaseRepository[DispatchLine]):
    model = DispatchLine

    async def list_by_dispatch(self, dispatch_id: uuid.UUID) -> list[DispatchLine]:
        result = await self.session.execute(
            sa.select(DispatchLine).where(DispatchLine.dispatch_id == dispatch_id)
        )
        return list(result.scalars().all())
