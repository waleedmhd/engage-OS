"""Procurement service — PO and GRN business logic.

Pattern: takes an AsyncSession, builds its own repositories, flushes writes.
Routers commit. The caller provides actor_id for audit context.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import InventoryEvents, emit_event_async
from app.core.exceptions import ConflictError, NotFoundError
from app.core.money import money, money_zero
from app.modules.procurement.constants import GRNStatus, POStatus
from app.modules.procurement.models import GoodsReceiptNote, PurchaseOrder
from app.modules.procurement.repository import (
    GRNLineRepository,
    GRNRepository,
    PurchaseOrderLineRepository,
    PurchaseOrderRepository,
)
from app.modules.procurement.schemas import (
    POLineResponse, GRNLineResponse,
    GRNCreateRequest,
    GRNResponse,
    POCreateRequest,
    POResponse,
)


def _po_response(po: PurchaseOrder) -> POResponse:
    """Build a POResponse including computed line responses."""
    return POResponse(
        id=po.id,
        po_no=po.po_no,
        supplier_id=po.supplier_id,
        currency_code=po.currency_code,
        status=po.status,
        order_date=po.order_date,
        expected_date=po.expected_date,
        remarks=po.remarks,
        created_at=po.created_at,
        updated_at=po.updated_at,
        lines=[POLineResponse.model_validate(line) for line in po.lines],
    )


def _grn_response(grn: GoodsReceiptNote) -> GRNResponse:
    """Build a GRNResponse including computed line responses."""
    return GRNResponse(
        id=grn.id,
        grn_no=grn.grn_no,
        po_id=grn.po_id,
        warehouse_id=grn.warehouse_id,
        receipt_date=grn.receipt_date,
        status=grn.status,
        je_id=grn.je_id,
        created_at=grn.created_at,
        updated_at=grn.updated_at,
        lines=[GRNLineResponse.model_validate(line) for line in grn.lines],
    )


# ===================================================================== POService


class POService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PurchaseOrderRepository(session)
        self._line_repo = PurchaseOrderLineRepository(session)

    # --------------------------------------------------------------------- reads

    async def get(self, po_id: uuid.UUID) -> PurchaseOrder:
        po = await self._repo.get_with_lines(po_id)
        if po is None:
            raise NotFoundError(f"PurchaseOrder {po_id} not found")
        return po

    async def list_pos(
        self,
        *,
        supplier_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PurchaseOrder]:
        return await self._repo.list_paginated(
            supplier_id=supplier_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    # -------------------------------------------------------------------- writes

    async def create(self, request: POCreateRequest) -> PurchaseOrder:
        """Create a draft purchase order with lines."""
        # Validate supplier exists.
        from app.modules.contacts.models import Contact

        supplier = await self._session.get(Contact, request.supplier_id)
        if supplier is None:
            raise NotFoundError(f"Supplier {request.supplier_id} not found")

        po_no = await self._repo.generate_po_no()

        po = await self._repo.create(
            po_no=po_no,
            supplier_id=request.supplier_id,
            currency_code=request.currency_code,
            status=POStatus.DRAFT.value,
            order_date=request.order_date,
            expected_date=request.expected_date,
            remarks=request.remarks,
        )

        for line_req in request.lines:
            line_total = money(line_req.qty * line_req.unit_cost)
            await self._line_repo.create(
                po_id=po.id,
                item_id=line_req.item_id,
                description=line_req.description or "",
                qty=line_req.qty,
                unit_cost=line_req.unit_cost,
                line_total=line_total,
            )

        return await self._repo.get_with_lines(po.id)  # type: ignore[return-value]

    async def issue(self, po_id: uuid.UUID, actor_id: uuid.UUID) -> PurchaseOrder:
        """Issue a draft purchase order."""
        po = await self._repo.get_with_lines(po_id)
        if po is None:
            raise NotFoundError(f"PurchaseOrder {po_id} not found")

        if po.status != POStatus.DRAFT.value:
            raise ConflictError(
                f"Cannot issue PO in '{po.status}' status. Must be 'draft'.",
                details={"po_id": str(po_id), "status": po.status},
            )

        await self._repo.update(po.id, status=POStatus.ISSUED.value)
        await self._session.flush()
        await self._session.refresh(po)
        return po


# ===================================================================== GRNService


class GRNService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = GRNRepository(session)
        self._line_repo = GRNLineRepository(session)

    # --------------------------------------------------------------------- reads

    async def get(self, grn_id: uuid.UUID) -> GoodsReceiptNote:
        grn = await self._repo.get_with_lines(grn_id)
        if grn is None:
            raise NotFoundError(f"GoodsReceiptNote {grn_id} not found")
        return grn

    async def list_grns(
        self,
        *,
        po_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GoodsReceiptNote]:
        return await self._repo.list_paginated(
            po_id=po_id,
            warehouse_id=warehouse_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    # -------------------------------------------------------------------- writes

    async def create(self, request: GRNCreateRequest) -> GoodsReceiptNote:
        """Create a draft GRN with lines."""
        # Validate PO if specified.
        if request.po_id is not None:
            po = await self._session.get(PurchaseOrder, request.po_id)
            if po is None:
                raise NotFoundError(f"PurchaseOrder {request.po_id} not found")

        grn_no = await self._repo.generate_grn_no()

        grn = await self._repo.create(
            grn_no=grn_no,
            po_id=request.po_id,
            warehouse_id=request.warehouse_id,
            receipt_date=request.receipt_date,
            status=GRNStatus.DRAFT.value,
        )

        for line_req in request.lines:
            line_total = money(line_req.qty_received * line_req.unit_cost)
            await self._line_repo.create(
                grn_id=grn.id,
                item_id=line_req.item_id,
                serial_no=line_req.serial_no,
                imei=line_req.imei,
                qty_received=line_req.qty_received,
                unit_cost=line_req.unit_cost,
                line_total=line_total,
            )

        return await self._repo.get_with_lines(grn.id)  # type: ignore[return-value]

    async def confirm(self, grn_id: uuid.UUID, actor_id: uuid.UUID) -> GoodsReceiptNote:
        """Confirm a draft GRN.

        On confirm:
        - Creates StockUnits for serialized items (one per serial_no).
        - Updates StockBalances for non-serialized items.
        - Creates StockLedgerEntries for every line.
        - Computes total_received_value.
        - Emits InventoryEvents.GRN_CONFIRMED so the bridge posts the journal.
        """
        grn = await self._repo.get_with_lines(grn_id)
        if grn is None:
            raise NotFoundError(f"GoodsReceiptNote {grn_id} not found")

        if grn.status != GRNStatus.DRAFT.value:
            raise ConflictError(
                f"Cannot confirm GRN in '{grn.status}' status. Must be 'draft'.",
                details={"grn_id": str(grn_id), "status": grn.status},
            )

        # Lazy imports — avoid circular dependencies at module level.
        from app.modules.inventory.constants import StockUnitStatus, StockVoucherType
        from app.modules.inventory.models import (
            StockBalance,
            StockLedgerEntry,
            StockUnit,
        )

        total_received_value = money_zero()

        for line in grn.lines:
            # Validate line has an item.
            if line.item_id is None:
                continue

            line_value = money(line.qty_received * line.unit_cost)
            total_received_value += line_value

            if line.serial_no:
                # Serialized item: create one StockUnit per serial_no.
                serial_numbers = [s.strip() for s in line.serial_no.split(",") if s.strip()]
                for sn in serial_numbers:
                    stock_unit = StockUnit(
                        item_id=line.item_id,
                        serial_no=sn,
                        status=StockUnitStatus.IN_STOCK.value,
                        purchase_cost=line.unit_cost,
                        grn_id=grn.id,
                    )
                    self._session.add(stock_unit)
                    await self._session.flush()

                    # Create StockLedgerEntry for this serialized unit.
                    sle = StockLedgerEntry(
                        posting_date=grn.receipt_date,
                        item_id=line.item_id,
                        warehouse_id=grn.warehouse_id,
                        stock_unit_id=stock_unit.id,
                        voucher_type=StockVoucherType.GRN.value,
                        voucher_id=grn.id,
                        qty_change=Decimal("1"),
                        valuation_rate=line.unit_cost,
                        stock_value_change=line.unit_cost,
                        qty_after=Decimal("1"),
                    )
                    self._session.add(sle)

            if line.qty_received > 0 and not line.serial_no:
                # Non-serialized item: update StockBalance (per item+location).
                # We need a default location to record the receipt.
                # Use the first location in the warehouse, or create a default.
                from app.modules.inventory.models import Location

                loc_stmt = sa.select(Location).where(
                    Location.warehouse_id == grn.warehouse_id,
                    Location.is_active == True,  # noqa: E712
                ).limit(1)
                loc_result = await self._session.execute(loc_stmt)
                location = loc_result.scalar_one_or_none()

                if location is None:
                    raise ConflictError(
                        f"No active location found in warehouse {grn.warehouse_id}. "
                        "Create at least one location before confirming GRNs.",
                        details={"warehouse_id": str(grn.warehouse_id)},
                    )

                balance_stmt = (
                    sa.select(StockBalance)
                    .where(
                        StockBalance.item_id == line.item_id,
                        StockBalance.location_id == location.id,
                    )
                )
                result = await self._session.execute(balance_stmt)
                balance = result.scalar_one_or_none()

                if balance is None:
                    balance = StockBalance(
                        item_id=line.item_id,
                        location_id=location.id,
                        qty=Decimal("0"),
                    )
                    self._session.add(balance)
                    await self._session.flush()

                balance.qty += line.qty_received
                qty_after = balance.qty

                # Create StockLedgerEntry.
                sle = StockLedgerEntry(
                    posting_date=grn.receipt_date,
                    item_id=line.item_id,
                    warehouse_id=grn.warehouse_id,
                    voucher_type=StockVoucherType.GRN.value,
                    voucher_id=grn.id,
                    qty_change=line.qty_received,
                    valuation_rate=line.unit_cost,
                    stock_value_change=line_value,
                    qty_after=qty_after,
                )
                self._session.add(sle)

        # Mark GRN as confirmed.
        await self._repo.update(grn.id, status=GRNStatus.CONFIRMED.value)
        await self._session.flush()

        # Emit the bridge event — MUST be awaited so the ledger bridge posts
        # the journal in the same transaction.
        await emit_event_async(
            InventoryEvents.GRN_CONFIRMED,
            session=self._session,
            grn_id=grn.id,
            grn_no=grn.grn_no,
            total_value=str(total_received_value),
            posting_date=grn.receipt_date,
            actor_id=actor_id,
        )

        # Re-load to pick up any je_id set by the bridge handler.
        await self._session.refresh(grn)

        # If the GRN is linked to a PO, check if all PO lines are now covered.
        if grn.po_id is not None:
            await self._maybe_receive_po(grn.po_id)

        return await self._repo.get_with_lines(grn.id)  # type: ignore[return-value]

    async def _maybe_receive_po(self, po_id: uuid.UUID) -> None:
        """Check if all PO lines are fully covered by confirmed GRNs.

        If so, mark the PO as RECEIVED.
        """
        from app.modules.procurement.models import GRNLine, PurchaseOrderLine

        po = await self._session.get(PurchaseOrder, po_id)
        if po is None or po.status != POStatus.ISSUED.value:
            return

        pol_result = await self._session.execute(
            sa.select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)
        )
        pol_lines = list(pol_result.scalars().all())

        all_covered = True
        for pol in pol_lines:
            if pol.item_id is None:
                continue
            # Sum GRN qty for this item across all confirmed GRNs for this PO.
            received_stmt = (
                sa.select(sa.func.coalesce(sa.func.sum(GRNLine.qty_received), 0))
                .join(GoodsReceiptNote, GRNLine.grn_id == GoodsReceiptNote.id)
                .where(
                    GoodsReceiptNote.po_id == po_id,
                    GRNLine.item_id == pol.item_id,
                    GoodsReceiptNote.status == GRNStatus.CONFIRMED.value,
                )
            )
            result = await self._session.execute(received_stmt)
            received_qty = Decimal(str(result.scalar_one()))
            if received_qty < pol.qty:
                all_covered = False
                break

        if all_covered:
            po_repo = PurchaseOrderRepository(self._session)
            await po_repo.update(po_id, status=POStatus.RECEIVED.value)
            await self._session.flush()
