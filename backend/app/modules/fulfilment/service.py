"""Fulfilment service — SO and Dispatch business logic.

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
from app.modules.fulfilment.constants import DispatchStatus, SOStatus
from app.modules.fulfilment.models import Dispatch, SalesOrder
from app.modules.fulfilment.repository import (
    DispatchLineRepository,
    DispatchRepository,
    SalesOrderLineRepository,
    SalesOrderRepository,
)
from app.modules.fulfilment.schemas import (
    DispatchCreateRequest,
    DispatchLineResponse,
    DispatchResponse,
    SOCreateRequest,
    SOLineResponse,
    SOResponse,
)


def _so_response(so: SalesOrder) -> SOResponse:
    """Build a SOResponse including computed line responses."""
    return SOResponse(
        id=so.id,
        so_no=so.so_no,
        customer_id=so.customer_id,
        currency_code=so.currency_code,
        status=so.status,
        order_date=so.order_date,
        created_at=so.created_at,
        updated_at=so.updated_at,
        lines=[SOLineResponse.model_validate(line) for line in so.lines],
    )


def _dispatch_response(dp: Dispatch) -> DispatchResponse:
    """Build a DispatchResponse including computed line responses."""
    return DispatchResponse(
        id=dp.id,
        dispatch_no=dp.dispatch_no,
        so_id=dp.so_id,
        dispatch_date=dp.dispatch_date,
        status=dp.status,
        je_id=dp.je_id,
        created_at=dp.created_at,
        updated_at=dp.updated_at,
        lines=[DispatchLineResponse.model_validate(line) for line in dp.lines],
    )


# ===================================================================== SOService


class SOService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SalesOrderRepository(session)
        self._line_repo = SalesOrderLineRepository(session)

    # --------------------------------------------------------------------- reads

    async def get(self, so_id: uuid.UUID) -> SalesOrder:
        so = await self._repo.get_with_lines(so_id)
        if so is None:
            raise NotFoundError(f"SalesOrder {so_id} not found")
        return so

    async def list_sos(
        self,
        *,
        customer_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SalesOrder]:
        return await self._repo.list_paginated(
            customer_id=customer_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    # -------------------------------------------------------------------- writes

    async def create(self, request: SOCreateRequest) -> SalesOrder:
        """Create a draft sales order with lines."""
        from app.modules.contacts.models import Contact

        customer = await self._session.get(Contact, request.customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {request.customer_id} not found")

        so_no = await self._repo.generate_so_no()

        so = await self._repo.create(
            so_no=so_no,
            customer_id=request.customer_id,
            currency_code=request.currency_code,
            status=SOStatus.DRAFT.value,
            order_date=request.order_date,
        )

        for line_req in request.lines:
            line_total = money(line_req.qty * line_req.unit_price)
            await self._line_repo.create(
                so_id=so.id,
                item_id=line_req.item_id,
                description=line_req.description or "",
                qty=line_req.qty,
                unit_price=line_req.unit_price,
                line_total=line_total,
            )

        return await self._repo.get_with_lines(so.id)  # type: ignore[return-value]

    async def confirm(self, so_id: uuid.UUID, actor_id: uuid.UUID) -> SalesOrder:
        """Confirm a draft sales order.

        Performs a credit check against the customer's credit_limit and
        outstanding AR before confirming.
        """
        so = await self._repo.get_with_lines(so_id)
        if so is None:
            raise NotFoundError(f"SalesOrder {so_id} not found")

        if so.status != SOStatus.DRAFT.value:
            raise ConflictError(
                f"Cannot confirm SO in '{so.status}' status. Must be 'draft'.",
                details={"so_id": str(so_id), "status": so.status},
            )

        # Credit check: sum the SO total and validate against available credit.
        so_total = money_zero()
        for line in so.lines:
            so_total += line.line_total

        from app.modules.receivables.service import check_credit_limit

        has_credit = await check_credit_limit(self._session, so.customer_id, so_total)
        if not has_credit:
            raise ConflictError(
                "Customer has insufficient available credit for this order.",
                details={
                    "customer_id": str(so.customer_id),
                    "so_total": str(so_total),
                },
            )

        await self._repo.update(so.id, status=SOStatus.CONFIRMED.value)
        await self._session.flush()
        await self._session.refresh(so)
        return so


# ===================================================================== DispatchService


class DispatchService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DispatchRepository(session)
        self._line_repo = DispatchLineRepository(session)

    # --------------------------------------------------------------------- reads

    async def get(self, dispatch_id: uuid.UUID) -> Dispatch:
        dp = await self._repo.get_with_lines(dispatch_id)
        if dp is None:
            raise NotFoundError(f"Dispatch {dispatch_id} not found")
        return dp

    async def list_dispatches(
        self,
        *,
        so_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Dispatch]:
        return await self._repo.list_paginated(
            so_id=so_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    # -------------------------------------------------------------------- writes

    async def create(self, request: DispatchCreateRequest) -> Dispatch:
        """Create a draft dispatch with lines."""
        if request.so_id is not None:
            so = await self._session.get(SalesOrder, request.so_id)
            if so is None:
                raise NotFoundError(f"SalesOrder {request.so_id} not found")

        dispatch_no = await self._repo.generate_dispatch_no()

        dp = await self._repo.create(
            dispatch_no=dispatch_no,
            so_id=request.so_id,
            dispatch_date=request.dispatch_date,
            status=DispatchStatus.DRAFT.value,
        )

        for line_req in request.lines:
            await self._line_repo.create(
                dispatch_id=dp.id,
                stock_unit_id=line_req.stock_unit_id,
                item_id=line_req.item_id,
                qty=line_req.qty,
                unit_cost=line_req.unit_cost if line_req.unit_cost else money_zero(),
            )

        return await self._repo.get_with_lines(dp.id)  # type: ignore[return-value]

    async def confirm(self, dispatch_id: uuid.UUID, actor_id: uuid.UUID) -> Dispatch:
        """Confirm a draft dispatch.

        On confirm:
        - For serialized items (stock_unit_id), row-locks the stock_unit
          (SELECT FOR UPDATE), validates IN_STOCK, updates to SOLD,
          sets sales_dispatch_id.
        - For non-serialized items, updates stock_balance, creates SLE rows.
        - Computes total COGS (sum of each unit's purchase_cost).
        - Emits InventoryEvents.UNIT_DISPATCHED so bridge posts the journal.
        """
        dp = await self._repo.get_with_lines(dispatch_id)
        if dp is None:
            raise NotFoundError(f"Dispatch {dispatch_id} not found")

        if dp.status != DispatchStatus.DRAFT.value:
            raise ConflictError(
                f"Cannot confirm dispatch in '{dp.status}' status. Must be 'draft'.",
                details={"dispatch_id": str(dispatch_id), "status": dp.status},
            )

        from app.modules.inventory.constants import StockUnitStatus, StockVoucherType
        from app.modules.inventory.models import (
            StockBalance,
            StockLedgerEntry,
            StockUnit,
        )

        total_cogs = money_zero()

        for line in dp.lines:
            if line.stock_unit_id is not None:
                # Serialized item: row-lock the stock_unit and validate.
                lock_stmt = (
                    sa.select(StockUnit)
                    .with_for_update()
                    .where(StockUnit.id == line.stock_unit_id)
                )
                result = await self._session.execute(lock_stmt)
                stock_unit = result.scalar_one_or_none()

                if stock_unit is None:
                    raise NotFoundError(f"StockUnit {line.stock_unit_id} not found")

                if stock_unit.status != StockUnitStatus.IN_STOCK.value:
                    raise ConflictError(
                        f"StockUnit {stock_unit.id} is not IN_STOCK (current: {stock_unit.status}).",
                        details={
                            "stock_unit_id": str(stock_unit.id),
                            "status": stock_unit.status,
                        },
                    )

                # Update the stock unit to SOLD.
                stock_unit.status = StockUnitStatus.SOLD.value
                stock_unit.sales_dispatch_id = dp.id
                unit_cost = stock_unit.purchase_cost or money_zero()
                total_cogs += unit_cost

                # Create SLE for this serialized unit.
                sle = StockLedgerEntry(
                    posting_date=dp.dispatch_date,
                    item_id=stock_unit.item_id,
                    stock_unit_id=stock_unit.id,
                    voucher_type=StockVoucherType.DISPATCH.value,
                    voucher_id=dp.id,
                    qty_change=Decimal("-1"),
                    valuation_rate=unit_cost,
                    stock_value_change=-unit_cost,
                    qty_after=Decimal("0"),
                )
                self._session.add(sle)

            elif line.item_id is not None and line.qty > 0:
                # Non-serialized item: update stock_balance.
                # Find the stock balance entry that has enough qty.
                balance_stmt = (
                    sa.select(StockBalance)
                    .with_for_update()
                    .where(
                        StockBalance.item_id == line.item_id,
                    )
                    .where(StockBalance.qty >= line.qty)
                    .order_by(StockBalance.location_id)
                    .limit(1)
                )
                result = await self._session.execute(balance_stmt)
                balance = result.scalar_one_or_none()

                if balance is None:
                    raise ConflictError(
                        f"Insufficient stock for item {line.item_id}: "
                        f"no location has {line.qty} units available.",
                        details={
                            "item_id": str(line.item_id),
                            "qty_requested": str(line.qty),
                        },
                    )

                unit_cost = (
                    line.unit_cost if line.unit_cost and line.unit_cost > 0
                    else balance.avg_cost if balance.avg_cost > 0  # type: ignore[attr-defined]
                    else money_zero()
                )
                line_cogs = money(line.qty * unit_cost)
                total_cogs += line_cogs

                balance.qty -= line.qty  # type: ignore[attr-defined]
                qty_after = balance.qty  # type: ignore[attr-defined]

                # Look up the warehouse for the SLE via the location.
                from app.modules.inventory.models import Location

                location = await self._session.get(Location, balance.location_id)
                warehouse_id = location.warehouse_id if location else None

                # Create SLE for this non-serialized dispatch.
                sle = StockLedgerEntry(
                    posting_date=dp.dispatch_date,
                    item_id=line.item_id,
                    warehouse_id=warehouse_id,
                    voucher_type=StockVoucherType.DISPATCH.value,
                    voucher_id=dp.id,
                    qty_change=-line.qty,
                    valuation_rate=unit_cost,
                    stock_value_change=-line_cogs,
                    qty_after=qty_after,
                )
                self._session.add(sle)

        # Mark dispatch as confirmed.
        await self._repo.update(dp.id, status=DispatchStatus.CONFIRMED.value)
        await self._session.flush()

        # Emit the bridge event — MUST be awaited so the ledger bridge posts
        # the journal in the same transaction.
        await emit_event_async(
            InventoryEvents.UNIT_DISPATCHED,
            session=self._session,
            dispatch_id=dp.id,
            dispatch_no=dp.dispatch_no,
            cogs_total=str(total_cogs),
            posting_date=dp.dispatch_date,
            actor_id=actor_id,
        )

        # Re-load to pick up any je_id set by the bridge handler.
        await self._session.refresh(dp)

        # If the dispatch is linked to an SO, check if fully dispatched.
        if dp.so_id is not None:
            await self._maybe_mark_so_dispatched(dp.so_id)

        return await self._repo.get_with_lines(dp.id)  # type: ignore[return-value]

    async def _maybe_mark_so_dispatched(self, so_id: uuid.UUID) -> None:
        """Check if all SO lines are fully covered by confirmed dispatches.

        If so, mark the SO as DISPATCHED.
        """
        from app.modules.fulfilment.models import DispatchLine, SalesOrderLine

        so = await self._session.get(SalesOrder, so_id)
        if so is None or so.status != SOStatus.CONFIRMED.value:
            return

        sol_result = await self._session.execute(
            sa.select(SalesOrderLine).where(SalesOrderLine.so_id == so_id)
        )
        sol_lines = list(sol_result.scalars().all())

        all_dispatched = True
        for sol in sol_lines:
            if sol.item_id is None:
                continue
            # Sum dispatched qty for this item across all confirmed dispatches.
            dispatched_stmt = (
                sa.select(sa.func.coalesce(sa.func.sum(DispatchLine.qty), 0))
                .join(Dispatch, DispatchLine.dispatch_id == Dispatch.id)
                .where(
                    Dispatch.so_id == so_id,
                    DispatchLine.item_id == sol.item_id,
                    Dispatch.status == DispatchStatus.CONFIRMED.value,
                )
            )
            result = await self._session.execute(dispatched_stmt)
            dispatched_qty = Decimal(str(result.scalar_one()))
            if dispatched_qty < sol.qty:
                all_dispatched = False
                break

        if all_dispatched:
            so_repo = SalesOrderRepository(self._session)
            await so_repo.update(so_id, status=SOStatus.DISPATCHED.value)
            await self._session.flush()
