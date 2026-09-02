"""Inventory endpoints — items, warehouses, stock, valuation.

Router commits after each mutating operation.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDB, DbSession
from app.core.dependencies import require_permission
from app.modules.inventory.schemas import (
    ItemCreateRequest,
    ItemResponse,
    LocationCreateRequest,
    LocationResponse,
    SerialLookupResponse,
    StockAdjustmentRequest,
    StockLedgerEntryResponse,
    StockOnHandResponse,
    StockReconciliationResponse,
    StockTransferRequest,
    StockUnitResponse,
    StockValuationResponse,
    WarehouseCreateRequest,
    WarehouseResponse,
)
from app.modules.inventory.service import (
    ItemService,
    LocationService,
    StockService,
    ValuationService,
    WarehouseService,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])

# ----------------------------------------------------------------------- Items


@router.post(
    "/items",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_item(
    payload: ItemCreateRequest,
    session: DbSession,
    _user=Depends(require_permission("erp_inv.item.manage")),
) -> ItemResponse:
    """Create a new inventory item."""
    service = ItemService(session)
    item = await service.create(payload)
    await session.commit()
    return ItemResponse.model_validate(item)


@router.get(
    "/items/{item_id}",
    response_model=ItemResponse,
)
async def get_item(
    item_id: uuid.UUID,
    session: DbSession,
    _user=Depends(require_permission("erp_inv.item.manage")),
) -> ItemResponse:
    """Get an inventory item by ID."""
    service = ItemService(session)
    item = await service.get(item_id)
    return ItemResponse.model_validate(item)


@router.get(
    "/items",
    response_model=list[ItemResponse],
)
async def list_items(
    session: DbSession,
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_permission("erp_inv.item.manage")),
) -> list[ItemResponse]:
    """List inventory items, optionally filtered by category."""
    service = ItemService(session)
    if category is not None:
        items = await service._repo.list_by_category(category)
    else:
        items = await service.list_active()
    # Simple slicing for now.
    sliced = items[offset : offset + limit]
    return [ItemResponse.model_validate(it) for it in sliced]


# ------------------------------------------------------------------- Warehouses


@router.post(
    "/warehouses",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_warehouse(
    payload: WarehouseCreateRequest,
    session: DbSession,
    _user=Depends(require_permission("erp_inv.item.manage")),
) -> WarehouseResponse:
    """Create a new warehouse."""
    service = WarehouseService(session)
    warehouse = await service.create(payload)
    await session.commit()
    return WarehouseResponse.model_validate(warehouse)


@router.get(
    "/warehouses",
    response_model=list[WarehouseResponse],
)
async def list_warehouses(
    session: DbSession,
    _user=Depends(require_permission("erp_inv.item.manage")),
) -> list[WarehouseResponse]:
    """List all active warehouses."""
    service = WarehouseService(session)
    warehouses = await service.list_active()
    return [WarehouseResponse.model_validate(w) for w in warehouses]


# ------------------------------------------------------------------- Locations


@router.post(
    "/locations",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_location(
    payload: LocationCreateRequest,
    session: DbSession,
    _user=Depends(require_permission("erp_inv.item.manage")),
) -> LocationResponse:
    """Create a new location within a warehouse."""
    service = LocationService(session)
    location = await service.create(payload)
    await session.commit()
    return location


# ---------------------------------------------------------------------- Stock


@router.get(
    "/stock",
    response_model=list[StockOnHandResponse],
)
async def stock_on_hand(
    session: DbSession,
    item_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_permission("erp_inv.stock.view")),
) -> list[StockOnHandResponse]:
    """Stock on hand report — item qty and value per location."""
    import sqlalchemy as sa

    from app.modules.inventory.models import Item, Location, StockBalance, Warehouse

    stmt = (
        sa.select(
            StockBalance.item_id,
            Item.name.label("item_name"),
            Location.warehouse_id,
            StockBalance.location_id,
            Location.code.label("location_code"),
            StockBalance.qty,
            (StockBalance.qty * StockBalance.avg_cost).label("value"),
        )
        .join(Item, Item.id == StockBalance.item_id)
        .join(Location, Location.id == StockBalance.location_id)
        .where(StockBalance.qty > 0)
    )

    if item_id is not None:
        stmt = stmt.where(StockBalance.item_id == item_id)

    stmt = stmt.order_by(Item.name, Location.code).limit(limit).offset(offset)

    result = await session.execute(stmt)
    rows = result.all()

    return [
        StockOnHandResponse(
            item_id=row.item_id,
            item_name=row.item_name,
            warehouse_id=row.warehouse_id,
            location_id=row.location_id,
            location_code=row.location_code,
            qty=row.qty,
            value=row.value,
        )
        for row in rows
    ]


@router.get(
    "/stock/serial/{serial_no}",
    response_model=SerialLookupResponse,
)
async def serial_lookup(
    serial_no: str,
    session: DbSession,
    _user=Depends(require_permission("erp_inv.stock.view")),
) -> SerialLookupResponse:
    """Look up a serial number's lifecycle — movements, status, location."""
    import sqlalchemy as sa

    from app.modules.inventory.models import (
        Item,
        Location,
        SerialNo,
        StockLedgerEntry,
        StockUnit,
    )

    # Look up the CRM-level serial registry.
    serial_result = await session.execute(
        sa.select(SerialNo).where(SerialNo.serial_no == serial_no)
    )
    serial_entry = serial_result.scalar_one_or_none()

    # Also look up in stock_units.
    unit = None
    item_name = None
    if serial_entry is not None and serial_entry.item_id is not None:
        item = await session.get(Item, serial_entry.item_id)
        if item is not None:
            item_name = item.name

    unit_result = await session.execute(
        sa.select(StockUnit).where(StockUnit.serial_no == serial_no)
    )
    unit = unit_result.scalar_one_or_none()

    # Build lifecycle.
    from app.modules.inventory.schemas import SerialMovement

    lifecycle: list[SerialMovement] = []

    if unit is not None:
        sle_result = await session.execute(
            sa.select(StockLedgerEntry)
            .where(StockLedgerEntry.stock_unit_id == unit.id)
            .order_by(StockLedgerEntry.posting_date.asc())
        )
        for sle in sle_result.scalars().all():
            lifecycle.append(
                SerialMovement(
                    posting_date=sle.posting_date,
                    voucher_type=sle.voucher_type,
                    voucher_id=sle.voucher_id,
                    qty_change=sle.qty_change,
                    valuation_rate=sle.valuation_rate,
                    status_after=None,
                )
            )

    # Determine location string.
    location_str: str | None = None
    if unit is not None and unit.location_id is not None:
        loc = await session.get(Location, unit.location_id)
        if loc is not None:
            location_str = loc.code

    return SerialLookupResponse(
        serial_no=serial_no,
        item_id=serial_entry.item_id if serial_entry else None,
        item_name=item_name,
        status=(
            serial_entry.status
            if serial_entry
            else (unit.status if unit else "unknown")
        ),
        location=location_str,
        lifecycle=lifecycle,
    )


@router.post(
    "/stock/adjust",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def adjust_stock(
    payload: StockAdjustmentRequest,
    session: DbSession,
    user=Depends(require_permission("erp_inv.stock.adjust")),
) -> dict:
    """Adjust stock quantity for a bulk item (positive or negative)."""
    service = StockService(session)
    amount = await service.adjust_stock(payload, user.id)
    await session.commit()
    return {
        "adjustment_id": str(payload.adjustment_id),
        "amount": str(amount),
        "posting_date": payload.posting_date.isoformat(),
    }


@router.post(
    "/stock/transfer",
    response_model=list[StockUnitResponse],
    status_code=status.HTTP_200_OK,
)
async def transfer_stock(
    payload: StockTransferRequest,
    session: DbSession,
    _user=Depends(require_permission("erp_inv.stock.transfer")),
) -> list[StockUnitResponse]:
    """Transfer stock units between locations."""
    service = StockService(session)
    units = await service.transfer_units(payload)
    await session.commit()
    return [StockUnitResponse.model_validate(u) for u in units]


# ------------------------------------------------------------------- Valuation


@router.get(
    "/valuation",
    response_model=StockValuationResponse,
)
async def get_valuation(
    session: DbSession,
    _user=Depends(require_permission("erp_rep.statements.view")),
) -> StockValuationResponse:
    """Get current stock valuation (total value, item count)."""
    service = ValuationService(session)
    val = await service.compute_stock_value()
    return StockValuationResponse(
        total_value=val["total_value"],
        serialized_value=val["serialized_value"],
        bulk_value=val["bulk_value"],
        item_count=val["item_count"],
        last_reconciled_at=None,
    )


@router.get(
    "/valuation/reconcile",
    response_model=StockReconciliationResponse,
)
async def reconcile_valuation(
    session: DbSession,
    _user=Depends(require_permission("erp_rep.statements.view")),
) -> StockReconciliationResponse:
    """Reconcile stock value to GL account 1200."""
    service = ValuationService(session)
    result = await service.reconcile_to_gl()
    return StockReconciliationResponse(
        stock_value=result["stock_value"],
        gl_balance=result["gl_balance"],
        variance=result["variance"],
        reconciled=result["reconciled"],
    )
