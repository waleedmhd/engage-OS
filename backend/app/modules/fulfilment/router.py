"""Fulfilment endpoints.

Router commits after each mutating operation — same pattern as receivables.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUserDB, DbSession
from app.core.dependencies import require_permission
from app.modules.fulfilment.schemas import (
    DispatchCreateRequest,
    DispatchResponse,
    SOCreateRequest,
    SOResponse,
)
from app.modules.fulfilment.service import (
    DispatchService,
    SOService,
    _dispatch_response,
    _so_response,
)

_PC = "erp_ful"

router = APIRouter(prefix="/fulfilment", tags=["fulfilment"])

# ------------------------------------------------------------------- Sales Orders


@router.post(
    "/sales-orders",
    response_model=SOResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_so(
    payload: SOCreateRequest,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.so.create")),
) -> SOResponse:
    """Create a draft sales order with line items."""
    service = SOService(session)
    so = await service.create(payload)
    await session.commit()
    return _so_response(so)


@router.get(
    "/sales-orders",
    response_model=list[SOResponse],
)
async def list_sos(
    session: DbSession,
    customer_id: uuid.UUID | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_permission(f"{_PC}.so.read")),
) -> list[SOResponse]:
    """List sales orders, optionally filtered by customer and/or status."""
    service = SOService(session)
    sos = await service.list_sos(
        customer_id=customer_id,
        status=status_value,
        limit=limit,
        offset=offset,
    )
    return [_so_response(so) for so in sos]


@router.get(
    "/sales-orders/{so_id}",
    response_model=SOResponse,
)
async def get_so(
    so_id: uuid.UUID,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.so.read")),
) -> SOResponse:
    """Get a sales order with its lines."""
    service = SOService(session)
    so = await service.get(so_id)
    return _so_response(so)


@router.post(
    "/sales-orders/{so_id}/confirm",
    response_model=SOResponse,
)
async def confirm_so(
    so_id: uuid.UUID,
    session: DbSession,
    user=Depends(require_permission(f"{_PC}.so.approve")),
) -> SOResponse:
    """Confirm a draft sales order — credit check happens here."""
    service = SOService(session)
    so = await service.confirm(so_id, user.id)
    await session.commit()
    return _so_response(so)


# --------------------------------------------------------------------- Dispatches


@router.post(
    "/dispatches",
    response_model=DispatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dispatch(
    payload: DispatchCreateRequest,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.dispatch.create")),
) -> DispatchResponse:
    """Create a draft dispatch with line items."""
    service = DispatchService(session)
    dp = await service.create(payload)
    await session.commit()
    return _dispatch_response(dp)


@router.get(
    "/dispatches",
    response_model=list[DispatchResponse],
)
async def list_dispatches(
    session: DbSession,
    so_id: uuid.UUID | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_permission(f"{_PC}.dispatch.read")),
) -> list[DispatchResponse]:
    """List dispatches, optionally filtered by SO and/or status."""
    service = DispatchService(session)
    dps = await service.list_dispatches(
        so_id=so_id,
        status=status_value,
        limit=limit,
        offset=offset,
    )
    return [_dispatch_response(dp) for dp in dps]


@router.post(
    "/dispatches/{dispatch_id}/confirm",
    response_model=DispatchResponse,
)
async def confirm_dispatch(
    dispatch_id: uuid.UUID,
    session: DbSession,
    user=Depends(require_permission(f"{_PC}.dispatch.create")),
) -> DispatchResponse:
    """Confirm a draft dispatch — updates stock, posts journal via bridge."""
    service = DispatchService(session)
    dp = await service.confirm(dispatch_id, user.id)
    await session.commit()
    return _dispatch_response(dp)
