"""Procurement endpoints.

Router commits after each mutating operation — same pattern as receivables.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUserDB, DbSession
from app.core.dependencies import require_permission
from app.modules.procurement.schemas import (
    GRNCreateRequest,
    GRNResponse,
    POCreateRequest,
    POResponse,
)
from app.modules.procurement.service import GRNService, POService, _grn_response, _po_response

_PC = "erp_proc"

router = APIRouter(prefix="/procurement", tags=["procurement"])

# ---------------------------------------------------------------- Purchase Orders


@router.post(
    "/purchase-orders",
    response_model=POResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_po(
    payload: POCreateRequest,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.po.create")),
) -> POResponse:
    """Create a draft purchase order with line items."""
    service = POService(session)
    po = await service.create(payload)
    await session.commit()
    return _po_response(po)


@router.get(
    "/purchase-orders",
    response_model=list[POResponse],
)
async def list_pos(
    session: DbSession,
    supplier_id: uuid.UUID | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_permission(f"{_PC}.po.read")),
) -> list[POResponse]:
    """List purchase orders, optionally filtered by supplier and/or status."""
    service = POService(session)
    pos = await service.list_pos(
        supplier_id=supplier_id,
        status=status_value,
        limit=limit,
        offset=offset,
    )
    return [_po_response(po) for po in pos]


@router.get(
    "/purchase-orders/{po_id}",
    response_model=POResponse,
)
async def get_po(
    po_id: uuid.UUID,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.po.read")),
) -> POResponse:
    """Get a purchase order with its lines."""
    service = POService(session)
    po = await service.get(po_id)
    return _po_response(po)


@router.post(
    "/purchase-orders/{po_id}/issue",
    response_model=POResponse,
)
async def issue_po(
    po_id: uuid.UUID,
    session: DbSession,
    user=Depends(require_permission(f"{_PC}.po.approve")),
) -> POResponse:
    """Issue a draft purchase order."""
    service = POService(session)
    po = await service.issue(po_id, user.id)
    await session.commit()
    return _po_response(po)


# ------------------------------------------------------------- Goods Receipt Notes


@router.post(
    "/grns",
    response_model=GRNResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_grn(
    payload: GRNCreateRequest,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.grn.create")),
) -> GRNResponse:
    """Create a draft goods receipt note with line items."""
    service = GRNService(session)
    grn = await service.create(payload)
    await session.commit()
    return _grn_response(grn)


@router.get(
    "/grns",
    response_model=list[GRNResponse],
)
async def list_grns(
    session: DbSession,
    po_id: uuid.UUID | None = Query(default=None),
    warehouse_id: uuid.UUID | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_permission(f"{_PC}.grn.read")),
) -> list[GRNResponse]:
    """List goods receipt notes, optionally filtered."""
    service = GRNService(session)
    grns = await service.list_grns(
        po_id=po_id,
        warehouse_id=warehouse_id,
        status=status_value,
        limit=limit,
        offset=offset,
    )
    return [_grn_response(grn) for grn in grns]


@router.post(
    "/grns/{grn_id}/confirm",
    response_model=GRNResponse,
)
async def confirm_grn(
    grn_id: uuid.UUID,
    session: DbSession,
    user=Depends(require_permission(f"{_PC}.grn.create")),
) -> GRNResponse:
    """Confirm a draft GRN — creates stock units, updates balances, posts journal."""
    service = GRNService(session)
    grn = await service.confirm(grn_id, user.id)
    await session.commit()
    return _grn_response(grn)
