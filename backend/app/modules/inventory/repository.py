"""Inventory repositories — items, warehouses, stock units, balances, ledger."""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import BaseRepository
from app.modules.inventory.models import (
    Item,
    Location,
    SerialNo,
    StockBalance,
    StockLedgerEntry,
    StockUnit,
    Warehouse,
)


class ItemRepository(BaseRepository[Item]):
    model = Item

    async def get_by_sku(self, sku: str) -> Item | None:
        result = await self.session.execute(
            sa.select(Item).where(Item.sku == sku)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Item]:
        result = await self.session.execute(
            sa.select(Item)
            .where(Item.is_active == True)  # noqa: E712
            .order_by(Item.name)
        )
        return list(result.scalars().all())

    async def list_by_category(self, category: str) -> list[Item]:
        result = await self.session.execute(
            sa.select(Item)
            .where(Item.category == category, Item.is_active == True)  # noqa: E712
            .order_by(Item.name)
        )
        return list(result.scalars().all())


class WarehouseRepository(BaseRepository[Warehouse]):
    model = Warehouse

    async def get_by_code(self, code: str) -> Warehouse | None:
        result = await self.session.execute(
            sa.select(Warehouse).where(Warehouse.code == code)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Warehouse]:
        result = await self.session.execute(
            sa.select(Warehouse)
            .where(Warehouse.is_active == True)  # noqa: E712
            .order_by(Warehouse.name)
        )
        return list(result.scalars().all())


class LocationRepository(BaseRepository[Location]):
    model = Location

    async def get_by_code(self, warehouse_id: uuid.UUID, code: str) -> Location | None:
        result = await self.session.execute(
            sa.select(Location).where(
                Location.warehouse_id == warehouse_id,
                Location.code == code,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_warehouse(self, warehouse_id: uuid.UUID) -> list[Location]:
        result = await self.session.execute(
            sa.select(Location)
            .where(
                Location.warehouse_id == warehouse_id,
                Location.is_active == True,  # noqa: E712
            )
            .order_by(Location.code)
        )
        return list(result.scalars().all())


class StockUnitRepository(BaseRepository[StockUnit]):
    model = StockUnit

    async def get_by_serial(self, serial_no: str) -> StockUnit | None:
        result = await self.session.execute(
            sa.select(StockUnit).where(StockUnit.serial_no == serial_no)
        )
        return result.scalar_one_or_none()

    async def list_by_item(self, item_id: uuid.UUID) -> list[StockUnit]:
        result = await self.session.execute(
            sa.select(StockUnit)
            .where(StockUnit.item_id == item_id)
            .order_by(StockUnit.serial_no)
        )
        return list(result.scalars().all())

    async def list_by_location(
        self, location_id: uuid.UUID
    ) -> list[StockUnit]:
        result = await self.session.execute(
            sa.select(StockUnit)
            .where(StockUnit.location_id == location_id)
            .order_by(StockUnit.serial_no)
        )
        return list(result.scalars().all())

    async def list_by_status(self, status: str) -> list[StockUnit]:
        result = await self.session.execute(
            sa.select(StockUnit)
            .where(StockUnit.status == status)
            .order_by(StockUnit.serial_no)
        )
        return list(result.scalars().all())

    async def acquire_for_dispatch(
        self, stock_unit_ids: list[uuid.UUID]
    ) -> list[StockUnit]:
        """SELECT ... FOR UPDATE row-lock on a set of stock units for dispatch.

        Prevents double-allocation: two concurrent dispatches cannot grab the
        same unit. The caller must validate status == IN_STOCK and update it
        within the same transaction.
        """
        if not stock_unit_ids:
            return []
        stmt = (
            sa.select(StockUnit)
            .where(StockUnit.id.in_(stock_unit_ids))
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class StockBalanceRepository(BaseRepository[StockBalance]):
    model = StockBalance

    async def get_for_item_location(
        self, item_id: uuid.UUID, location_id: uuid.UUID
    ) -> StockBalance | None:
        result = await self.session.execute(
            sa.select(StockBalance).where(
                StockBalance.item_id == item_id,
                StockBalance.location_id == location_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_balance(
        self,
        item_id: uuid.UUID,
        location_id: uuid.UUID,
        qty_change: Decimal,
        avg_cost: Decimal | None = None,
    ) -> StockBalance:
        """Increment/decrement qty and optionally update avg_cost.

        Uses a SELECT then INSERT-or-UPDATE approach within a single
        transaction row-lock to avoid race conditions.
        """
        # Lock the row if it exists.
        existing = await self.session.execute(
            sa.select(StockBalance)
            .where(
                StockBalance.item_id == item_id,
                StockBalance.location_id == location_id,
            )
            .with_for_update()
        )
        balance = existing.scalar_one_or_none()

        if balance is None:
            balance = await self.create(
                item_id=item_id,
                location_id=location_id,
                qty=qty_change,
                avg_cost=avg_cost or Decimal("0"),
            )
        else:
            new_qty = balance.qty + qty_change
            update_kwargs: dict = {"qty": new_qty}
            if avg_cost is not None:
                update_kwargs["avg_cost"] = avg_cost
            balance = await self.update(balance.id, **update_kwargs)

        return balance  # type: ignore[return-value]

    async def update_avg_cost(
        self, item_id: uuid.UUID, location_id: uuid.UUID, avg_cost: Decimal
    ) -> StockBalance | None:
        """Update only the average cost for an item+location pair."""
        existing = await self.get_for_item_location(item_id, location_id)
        if existing is None:
            return None
        return await self.update(existing.id, avg_cost=avg_cost)


class StockLedgerEntryRepository(BaseRepository[StockLedgerEntry]):
    model = StockLedgerEntry

    async def list_by_item(
        self,
        item_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StockLedgerEntry]:
        result = await self.session.execute(
            sa.select(StockLedgerEntry)
            .where(StockLedgerEntry.item_id == item_id)
            .order_by(StockLedgerEntry.posting_date.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_stock_unit(
        self, stock_unit_id: uuid.UUID
    ) -> list[StockLedgerEntry]:
        result = await self.session.execute(
            sa.select(StockLedgerEntry)
            .where(StockLedgerEntry.stock_unit_id == stock_unit_id)
            .order_by(StockLedgerEntry.posting_date.asc())
        )
        return list(result.scalars().all())

    async def get_qty_after(
        self, item_id: uuid.UUID, location_id: uuid.UUID | None = None
    ) -> Decimal:
        """Return the latest qty_after for a given item (and optionally location).

        Used to materialize the current balance from ledger entries.
        """
        stmt = (
            sa.select(StockLedgerEntry.qty_after)
            .where(
                StockLedgerEntry.item_id == item_id,
                StockLedgerEntry.is_cancelled == False,  # noqa: E712
            )
            .order_by(StockLedgerEntry.posting_date.desc())
            .limit(1)
        )
        if location_id is not None:
            stmt = stmt.where(
                StockLedgerEntry.warehouse_id == location_id
            )
        result = await self.session.execute(stmt)
        val = result.scalar_one_or_none()
        return Decimal(str(val)) if val is not None else Decimal("0")


class SerialNoRepository(BaseRepository[SerialNo]):
    model = SerialNo

    async def get_by_serial(self, serial_no: str) -> SerialNo | None:
        result = await self.session.execute(
            sa.select(SerialNo).where(SerialNo.serial_no == serial_no)
        )
        return result.scalar_one_or_none()

    async def create_serial(
        self,
        serial_no: str,
        item_id: uuid.UUID,
        status: str,
        warehouse_id: uuid.UUID | None = None,
        purchase_rate: Decimal | None = None,
    ) -> SerialNo:
        return await self.create(
            serial_no=serial_no,
            item_id=item_id,
            status=status,
            warehouse_id=warehouse_id,
            purchase_rate=purchase_rate,
        )

    async def update_status(
        self,
        id: uuid.UUID,
        status: str,
        **kwargs: object,
    ) -> SerialNo | None:
        return await self.update(id, status=status, **kwargs)
