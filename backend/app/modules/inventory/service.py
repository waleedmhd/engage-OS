"""Inventory service — items, warehouses, stock, valuation.

Pattern: takes an AsyncSession, builds its own repositories, flushes writes.
Routers commit. The caller provides actor_id for audit context.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import InventoryEvents, emit_event_async
from app.core.exceptions import ConflictError, NotFoundError
from app.core.money import money, money_sum, qty
from app.modules.inventory.constants import (
    AdjustmentReason,
    StockUnitStatus,
    StockVoucherType,
    TransferStatus,
)
from app.modules.inventory.models import (
    Item,
    SerialNo,
    StockBalance,
    StockLedgerEntry,
    StockUnit,
    Warehouse,
)
from app.modules.inventory.repository import (
    ItemRepository,
    LocationRepository,
    SerialNoRepository,
    StockBalanceRepository,
    StockLedgerEntryRepository,
    StockUnitRepository,
    WarehouseRepository,
)
from app.modules.inventory.schemas import (
    ItemCreateRequest,
    LocationCreateRequest,
    LocationResponse,
    StockAdjustmentRequest,
    StockTransferRequest,
    WarehouseCreateRequest,
)


# ===================================================================== ItemService


class ItemService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ItemRepository(session)

    async def create(self, request: ItemCreateRequest) -> Item:
        existing = await self._repo.get_by_sku(request.sku)
        if existing is not None:
            raise ConflictError(
                f"Item with SKU '{request.sku}' already exists.",
                details={"sku": request.sku},
            )
        return await self._repo.create(
            sku=request.sku,
            name=request.name,
            brand=request.brand,
            model=request.model,
            category=request.category,
            nature=request.nature,
            uom_id=request.uom_id,
            valuation_method=request.valuation_method,
            reorder_level=request.reorder_level,
            reorder_qty=qty(request.reorder_qty),
            default_purchase_price=money(request.default_purchase_price),
            default_sale_price=money(request.default_sale_price),
            inventory_account_id=request.inventory_account_id,
            cogs_account_id=request.cogs_account_id,
            revenue_account_id=request.revenue_account_id,
            is_sales_item=request.is_sales_item,
            is_purchase_item=request.is_purchase_item,
            end_of_life=request.end_of_life,
            lead_time_days=request.lead_time_days,
            safety_stock=(
                qty(request.safety_stock) if request.safety_stock is not None else None
            ),
            weight_per_unit=request.weight_per_unit,
            weight_uom_id=request.weight_uom_id,
            country_of_origin=request.country_of_origin,
            customs_tariff_number=request.customs_tariff_number,
            description=request.description,
        )

    async def get(self, item_id: uuid.UUID) -> Item:
        return await self._repo.get_or_404(item_id)

    async def update(
        self, item_id: uuid.UUID, **kwargs: object
    ) -> Item:
        result = await self._repo.update(item_id, **kwargs)
        if result is None:
            raise NotFoundError(f"Item {item_id} not found")
        return result

    async def deactivate(self, item_id: uuid.UUID) -> Item:
        result = await self._repo.update(item_id, is_active=False)
        if result is None:
            raise NotFoundError(f"Item {item_id} not found")
        return result

    async def list_active(self) -> list[Item]:
        return await self._repo.list_active()


# ================================================================= WarehouseService


class WarehouseService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = WarehouseRepository(session)

    async def create(self, request: WarehouseCreateRequest) -> Warehouse:
        existing = await self._repo.get_by_code(request.code)
        if existing is not None:
            raise ConflictError(
                f"Warehouse with code '{request.code}' already exists.",
                details={"code": request.code},
            )
        return await self._repo.create(
            name=request.name,
            code=request.code,
        )

    async def get(self, warehouse_id: uuid.UUID) -> Warehouse:
        return await self._repo.get_or_404(warehouse_id)

    async def list_active(self) -> list[Warehouse]:
        return await self._repo.list_active()


# ============================================================ Location Sub-service


class LocationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = LocationRepository(session)
        self._warehouse_repo = WarehouseRepository(session)

    async def create(self, request: LocationCreateRequest) -> LocationResponse:
        warehouse = await self._warehouse_repo.get_by_code(request.warehouse_code)
        if warehouse is None:
            raise NotFoundError(
                f"Warehouse '{request.warehouse_code}' not found."
            )

        existing = await self._repo.get_by_code(warehouse.id, request.code)
        if existing is not None:
            raise ConflictError(
                f"Location '{request.code}' already exists in warehouse "
                f"'{request.warehouse_code}'.",
                details={"warehouse_code": request.warehouse_code, "code": request.code},
            )

        from app.modules.inventory.models import Location

        location = Location(
            warehouse_id=warehouse.id,
            code=request.code,
        )
        self._session.add(location)
        await self._session.flush()
        await self._session.refresh(location)
        return LocationResponse(
            id=location.id,
            warehouse_id=location.warehouse_id,
            warehouse_code=request.warehouse_code,
            code=location.code,
            is_active=location.is_active,
        )


# ===================================================================== StockService


class StockService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._stock_unit_repo = StockUnitRepository(session)
        self._balance_repo = StockBalanceRepository(session)
        self._ledger_repo = StockLedgerEntryRepository(session)
        self._serial_no_repo = SerialNoRepository(session)

    # ---------------------------------------------------------------- receive

    async def receive_into_stock(
        self,
        grn_id: uuid.UUID,
        items: list[dict],
        posting_date: date,
    ) -> list[dict]:
        """Receive items from a GRN into stock.

        Each item dict: {item_id, location_id, warehouse_id, qty, purchase_cost,
                         serial_nos (optional list of serial_no strings),
                         imei (optional)}.

        Creates StockUnits for serialized items and StockLedgerEntries for all.
        Updates StockBalances.
        Returns a list of created StockUnit dicts for bridge emission.
        """
        result_units: list[dict] = []

        for line in items:
            item_id = line["item_id"]
            location_id = line.get("location_id")
            warehouse_id = line.get("warehouse_id")
            line_qty = qty(line["qty"])
            purchase_cost = money(line.get("purchase_cost", 0))
            serial_nos: list[str] = line.get("serial_nos") or []
            imei: str | None = line.get("imei")

            item = await self._session.get(Item, item_id)
            if item is None:
                raise NotFoundError(f"Item {item_id} not found")

            is_serialized = item.nature == "serialized"

            if is_serialized:
                for sno in serial_nos:
                    # Check serial uniqueness.
                    existing_unit = await self._stock_unit_repo.get_by_serial(sno)
                    if existing_unit is not None:
                        raise ConflictError(
                            f"Serial '{sno}' already exists in stock.",
                            details={"serial_no": sno},
                        )

                    unit = await self._stock_unit_repo.create(
                        item_id=item_id,
                        serial_no=sno,
                        imei=imei,
                        status=StockUnitStatus.IN_STOCK.value,
                        location_id=location_id,
                        purchase_cost=purchase_cost,
                        grn_id=grn_id,
                    )

                    # Create CRM-level serial registry entry.
                    await self._serial_no_repo.create_serial(
                        serial_no=sno,
                        item_id=item_id,
                        status=StockUnitStatus.IN_STOCK.value,
                        warehouse_id=warehouse_id,
                        purchase_rate=purchase_cost,
                    )

                    # Stock ledger entry.
                    qty_before = await self._ledger_repo.get_qty_after(
                        item_id, location_id
                    )
                    qty_after = qty_before + Decimal("1")
                    await self._ledger_repo.create(
                        posting_date=posting_date,
                        item_id=item_id,
                        warehouse_id=warehouse_id,
                        stock_unit_id=unit.id,
                        voucher_type=StockVoucherType.GRN.value,
                        voucher_id=grn_id,
                        qty_change=Decimal("1"),
                        valuation_rate=purchase_cost,
                        stock_value_change=purchase_cost,
                        qty_after=qty_after,
                    )

                    # Upsert stock balance.
                    if location_id is not None:
                        await self._balance_repo.upsert_balance(
                            item_id, location_id, Decimal("1"), purchase_cost
                        )

                    result_units.append(
                        {
                            "stock_unit_id": unit.id,
                            "serial_no": sno,
                            "item_id": item_id,
                            "purchase_cost": purchase_cost,
                            "location_id": location_id,
                        }
                    )
            else:
                # Bulk item — single ledger entry, no stock unit.
                qty_before = await self._ledger_repo.get_qty_after(
                    item_id, location_id
                )
                qty_after_val = qty_before + line_qty
                value_change = line_qty * purchase_cost

                await self._ledger_repo.create(
                    posting_date=posting_date,
                    item_id=item_id,
                    warehouse_id=warehouse_id,
                    stock_unit_id=None,
                    voucher_type=StockVoucherType.GRN.value,
                    voucher_id=grn_id,
                    qty_change=line_qty,
                    valuation_rate=purchase_cost,
                    stock_value_change=money(value_change),
                    qty_after=qty_after_val,
                )

                if location_id is not None:
                    await self._balance_repo.upsert_balance(
                        item_id, location_id, line_qty, purchase_cost
                    )

        await self._session.flush()
        return result_units

    # --------------------------------------------------------------- dispatch

    async def dispatch_units(
        self,
        stock_unit_ids: list[uuid.UUID],
        dispatch_id: uuid.UUID,
        posting_date: date,
    ) -> Decimal:
        """Dispatch serialized units (row-locked), update status to SOLD, create SLE rows.

        Returns total COGS for the dispatch (sum of purchase_cost of all units).
        The caller should emit UNIT_DISPATCHED with the total COGS for bridge posting.
        """
        units = await self._stock_unit_repo.acquire_for_dispatch(stock_unit_ids)

        if len(units) != len(stock_unit_ids):
            found_ids = {u.id for u in units}
            missing = [str(uid) for uid in stock_unit_ids if uid not in found_ids]
            raise NotFoundError(
                f"Stock units not found: {missing}",
                details={"missing": missing},
            )

        total_cogs = money(Decimal("0"))

        for unit in units:
            if unit.status != StockUnitStatus.IN_STOCK.value:
                raise ConflictError(
                    f"Stock unit {unit.serial_no} is not IN_STOCK "
                    f"(current status: {unit.status}).",
                    details={
                        "stock_unit_id": str(unit.id),
                        "serial_no": unit.serial_no,
                        "status": unit.status,
                    },
                )

            # Update unit status.
            await self._stock_unit_repo.update(
                unit.id,
                status=StockUnitStatus.SOLD.value,
                sales_dispatch_id=dispatch_id,
            )

            # Update CRM serial registry.
            serial_entry = await self._serial_no_repo.get_by_serial(unit.serial_no)
            if serial_entry is not None:
                await self._serial_no_repo.update_status(
                    serial_entry.id,
                    StockUnitStatus.SOLD.value,
                )

            # Stock ledger entry.
            qty_before = await self._ledger_repo.get_qty_after(
                unit.item_id, unit.location_id
            )
            qty_after = qty_before - Decimal("1")

            await self._ledger_repo.create(
                posting_date=posting_date,
                item_id=unit.item_id,
                warehouse_id=None,
                stock_unit_id=unit.id,
                voucher_type=StockVoucherType.DISPATCH.value,
                voucher_id=dispatch_id,
                qty_change=Decimal("-1"),
                valuation_rate=unit.purchase_cost,
                stock_value_change=money(-unit.purchase_cost),
                qty_after=qty_after,
            )

            # Deduct from balance.
            if unit.location_id is not None:
                await self._balance_repo.upsert_balance(
                    unit.item_id, unit.location_id, Decimal("-1")
                )

            total_cogs += unit.purchase_cost

        await self._session.flush()
        return money(total_cogs)

    # --------------------------------------------------------------- transfer

    async def transfer_units(
        self,
        request: StockTransferRequest,
    ) -> list[StockUnit]:
        """Transfer units between locations. Status becomes IN_TRANSIT."""
        units = await self._stock_unit_repo.acquire_for_dispatch(
            request.stock_unit_ids
        )

        if len(units) != len(request.stock_unit_ids):
            found_ids = {u.id for u in units}
            missing = [
                str(uid) for uid in request.stock_unit_ids if uid not in found_ids
            ]
            raise NotFoundError(
                f"Stock units not found: {missing}",
                details={"missing": missing},
            )

        updated: list[StockUnit] = []
        for unit in units:
            if unit.status != StockUnitStatus.IN_STOCK.value:
                raise ConflictError(
                    f"Stock unit {unit.serial_no} is not IN_STOCK.",
                    details={
                        "stock_unit_id": str(unit.id),
                        "serial_no": unit.serial_no,
                        "status": unit.status,
                    },
                )

            # Create a transfer ledger entry.
            await self._ledger_repo.create(
                posting_date=request.posting_date,
                item_id=unit.item_id,
                warehouse_id=None,
                stock_unit_id=unit.id,
                voucher_type=StockVoucherType.TRANSFER.value,
                voucher_id=request.transfer_id,
                qty_change=Decimal("0"),
                valuation_rate=unit.purchase_cost,
                stock_value_change=Decimal("0"),
                qty_after=Decimal("0"),
            )

            # Deduct from source location.
            if unit.location_id is not None:
                await self._balance_repo.upsert_balance(
                    unit.item_id, unit.location_id, Decimal("-1")
                )

            # Update location and status.
            result = await self._stock_unit_repo.update(
                unit.id,
                location_id=request.to_location_id,
                status=StockUnitStatus.IN_TRANSIT.value,
            )
            updated.append(result)  # type: ignore[arg-type]

        await self._session.flush()
        return updated

    # --------------------------------------------------------------- adjust

    async def adjust_stock(
        self,
        request: StockAdjustmentRequest,
        actor_id: uuid.UUID,
    ) -> Decimal:
        """Adjust stock qty for a bulk item at a location. Creates SLE row.

        Returns the adjustment amount (absolute value change * avg cost) for
        bridge emission.
        """
        item = await self._session.get(Item, request.item_id)
        if item is None:
            raise NotFoundError(f"Item {request.item_id} not found")

        if item.nature == "serialized":
            raise ConflictError(
                "Stock adjustment is not supported for serialized items. "
                "Use individual unit adjustments.",
                details={"item_id": str(request.item_id)},
            )

        qty_adjustment = qty(request.qty_adjustment)

        # Get current balance or zero.
        balance = await self._balance_repo.get_for_item_location(
            request.item_id, request.location_id
        )
        current_qty = balance.qty if balance else Decimal("0")
        avg_cost = balance.avg_cost if balance else money(item.default_purchase_price)

        qty_after = current_qty + qty_adjustment
        if qty_after < 0:
            raise ConflictError(
                f"Adjustment would result in negative stock ({qty_after}).",
                details={
                    "item_id": str(request.item_id),
                    "current_qty": str(current_qty),
                    "adjustment": str(qty_adjustment),
                },
            )

        adjustment_amount = money(abs(qty_adjustment) * avg_cost)

        # Create SLE.
        sle = await self._ledger_repo.create(
            posting_date=request.posting_date,
            item_id=request.item_id,
            warehouse_id=None,
            stock_unit_id=None,
            voucher_type=StockVoucherType.ADJUSTMENT.value,
            voucher_id=request.adjustment_id,
            qty_change=qty_adjustment,
            valuation_rate=avg_cost,
            stock_value_change=money(qty_adjustment * avg_cost),
            qty_after=qty_after,
        )

        # Upsert balance.
        await self._balance_repo.upsert_balance(
            request.item_id, request.location_id, qty_adjustment, avg_cost
        )

        await self._session.flush()

        # Emit adjustment event for bridge posting.
        await emit_event_async(
            InventoryEvents.ADJUSTMENT_CONFIRMED,
            session=self._session,
            adjustment_id=request.adjustment_id,
            sle_id=sle.id,
            amount=adjustment_amount,
            qty_adjustment=qty_adjustment,
            posting_date=request.posting_date,
            reason=request.reason_code,
            item_id=request.item_id,
            location_id=request.location_id,
            actor_id=actor_id,
        )

        return adjustment_amount


# ================================================================= ValuationService


class ValuationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._stock_unit_repo = StockUnitRepository(session)
        self._balance_repo = StockBalanceRepository(session)
        self._item_repo = ItemRepository(session)

    async def compute_stock_value(self) -> dict:
        """Compute total stock value: SUM(IN_STOCK units x purchase_cost)
        + SUM(bulk qty x avg_cost).

        Returns {total_value, serialized_value, bulk_value, item_count}. The
        two components were already computed here but discarded; the stock
        page renders them as separate cards.
        """
        # Serialized: SUM of purchase_cost for all IN_STOCK units.
        serial_stmt = sa.select(
            sa.func.coalesce(sa.func.sum(StockUnit.purchase_cost), 0)
        ).where(StockUnit.status == StockUnitStatus.IN_STOCK.value)
        serial_result = await self._session.execute(serial_stmt)
        serial_value = Decimal(str(serial_result.scalar_one()))

        # Bulk: SUM(qty * avg_cost) from stock_balances.
        bulk_stmt = sa.select(
            sa.func.coalesce(
                sa.func.sum(StockBalance.qty * StockBalance.avg_cost), 0
            )
        )
        bulk_result = await self._session.execute(bulk_stmt)
        bulk_value = Decimal(str(bulk_result.scalar_one()))

        total_value = money(serial_value + bulk_value)

        # Distinct item count.
        count_stmt = sa.select(sa.func.count()).select_from(
            sa.select(
                sa.func.coalesce(StockUnit.item_id, None).label("uid")
            )
            .where(StockUnit.status == StockUnitStatus.IN_STOCK.value)
            .union(
                sa.select(StockBalance.item_id.label("uid")).where(
                    StockBalance.qty > 0
                )
            )
            .subquery()
        )
        count_result = await self._session.execute(count_stmt)
        item_count = count_result.scalar_one()

        return {
            "total_value": total_value,
            "serialized_value": money(serial_value),
            "bulk_value": money(bulk_value),
            "item_count": item_count,
        }

    async def reconcile_to_gl(self) -> dict:
        """Compare stock value to GL account 1200 (Inventory) balance.

        Returns {stock_value, gl_balance, variance, reconciled}.
        """
        stock_val_result = await self.compute_stock_value()
        stock_value = stock_val_result["total_value"]

        # Query GL account 1200 balance from journal lines.
        # Account 1200 is the Inventory control account.
        gl_stmt = sa.text(
            """
            SELECT
                COALESCE(SUM(
                    CASE WHEN jl.dr_base > 0 THEN jl.dr_base ELSE -jl.cr_base END
                ), 0) AS balance
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.entry_id
            JOIN accounts a ON a.id = jl.account_id
            WHERE a.code = '1200'
              AND je.status = 'posted'
            """
        )
        gl_result = await self._session.execute(gl_stmt)
        gl_balance = Decimal(str(gl_result.scalar_one()))

        variance = money(stock_value - gl_balance)

        return {
            "stock_value": stock_value,
            "gl_balance": gl_balance,
            "variance": variance,
            "reconciled": abs(variance) < Decimal("0.005"),
        }

    async def recompute_moving_average(
        self, item_id: uuid.UUID
    ) -> dict[str, Decimal | str]:
        """Recompute the moving average cost for an item from its ledger entries.

        Moving average = SUM(value_change) / SUM(qty_change) for all positive
        receipts (GRN only) for this item. Returns {item_id, avg_cost}.
        """
        stmt = sa.select(
            sa.func.coalesce(
                sa.func.sum(StockLedgerEntry.stock_value_change), 0
            ),
            sa.func.coalesce(
                sa.func.sum(StockLedgerEntry.qty_change), 0
            ),
        ).where(
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.voucher_type == StockVoucherType.GRN.value,
            StockLedgerEntry.is_cancelled == False,  # noqa: E712
            StockLedgerEntry.qty_change > 0,
        )
        result = await self._session.execute(stmt)
        row = result.one()
        total_value = Decimal(str(row[0]))
        total_qty = Decimal(str(row[1]))

        avg_cost = money(
            total_value / total_qty if total_qty > 0 else Decimal("0")
        )

        return {"item_id": str(item_id), "avg_cost": avg_cost}
