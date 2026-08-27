"""Payables endpoints — supplier bills, payments, debit notes, ageing.

Auth: require_permission for each operation. Router commits the session after
mutating operations (same pattern as contacts and conversations).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUserDB, DbSession
from app.core.dependencies import require_permission
from app.modules.payables.schemas import (
    AgeingResponse,
    AllocationResponse,
    BillCreateRequest,
    BillResponse,
    DebitNoteCreateRequest,
    DebitNoteResponse,
    PaymentAllocationRequest,
    PaymentCreateRequest,
    PaymentResponse,
)
from app.modules.payables.service import BillService, DebitNoteService, PaymentService

router = APIRouter(prefix="/payables", tags=["payables"])


# ---------------------------------------------------------------- bills


@router.post(
    "/bills",
    response_model=BillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bill(
    payload: BillCreateRequest,
    session: DbSession,
    _user=Depends(require_permission("erp_ap.bill.create")),
) -> BillResponse:
    """Create a draft supplier bill."""
    service = BillService(session)
    bill = await service.create(payload)
    await session.commit()
    return BillResponse.model_validate(bill)


@router.post(
    "/bills/{bill_id}/issue",
    response_model=BillResponse,
)
async def issue_bill(
    bill_id: uuid.UUID,
    session: DbSession,
    current_user=Depends(require_permission("erp_ap.bill.create")),
) -> BillResponse:
    """Issue a draft bill and post the AP journal entry (Dr 2200 / Cr 2100)."""
    service = BillService(session)
    bill = await service.issue(bill_id, actor_id=current_user.id)
    await session.commit()
    return BillResponse.model_validate(bill)


@router.get("/bills/{bill_id}", response_model=BillResponse)
async def get_bill(
    bill_id: uuid.UUID,
    session: DbSession,
    _user=Depends(require_permission("erp_ap.bill.create")),
) -> BillResponse:
    """Get a supplier bill with its line items."""
    from app.modules.payables.repository import SupplierBillRepository

    repo = SupplierBillRepository(session)
    bill = await repo.get_with_lines(bill_id)
    if bill is None:
        raise HTTPException(status_code=404, detail="Bill not found")
    return BillResponse.model_validate(bill)


@router.get("/bills", response_model=list[BillResponse])
async def list_bills(
    session: DbSession,
    supplier_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    _user=Depends(require_permission("erp_ap.bill.create")),
) -> list[BillResponse]:
    """List supplier bills, optionally filtered by supplier and/or status."""
    from app.modules.payables.repository import SupplierBillRepository

    repo = SupplierBillRepository(session)
    if supplier_id is not None:
        bills = await repo.list_by_supplier(supplier_id, status=status)
    else:
        bills = await repo.list_outstanding(supplier_id=None)
    return [BillResponse.model_validate(b) for b in bills]


@router.post("/bills/{bill_id}/void", response_model=BillResponse)
async def void_bill(
    bill_id: uuid.UUID,
    session: DbSession,
    current_user=Depends(require_permission("erp_ap.bill.void")),
) -> BillResponse:
    """Void a supplier bill (only if not paid)."""
    service = BillService(session)
    bill = await service.void(bill_id, actor_id=current_user.id)
    await session.commit()
    return BillResponse.model_validate(bill)


# ---------------------------------------------------------------- payments


@router.post(
    "/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    payload: PaymentCreateRequest,
    session: DbSession,
    _user=Depends(require_permission("erp_ap.payment.create")),
) -> PaymentResponse:
    """Record a payment to a supplier."""
    service = PaymentService(session)
    payment = await service.create(payload)
    await session.commit()
    return PaymentResponse.model_validate(payment)


@router.post(
    "/payments/{payment_id}/allocate",
    response_model=AllocationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def allocate_payment(
    payment_id: uuid.UUID,
    payload: PaymentAllocationRequest,
    session: DbSession,
    _user=Depends(require_permission("erp_ap.payment.allocate")),
) -> AllocationResponse:
    """Allocate a payment (or portion) to a specific bill."""
    service = PaymentService(session)
    allocation = await service.allocate(payment_id, payload)
    await session.commit()
    return AllocationResponse.model_validate(allocation)


@router.get("/payments", response_model=list[PaymentResponse])
async def list_payments(
    session: DbSession,
    supplier_id: uuid.UUID | None = Query(None),
    _user=Depends(require_permission("erp_ap.payment.create")),
) -> list[PaymentResponse]:
    """List payments, optionally filtered by supplier."""
    from app.modules.payables.repository import SupplierPaymentRepository

    repo = SupplierPaymentRepository(session)
    if supplier_id is not None:
        payments = await repo.list_by_supplier(supplier_id)
    else:
        payments = list(await repo.list())
    return [PaymentResponse.model_validate(p) for p in payments]


# ---------------------------------------------------------------- ageing


@router.get("/ageing", response_model=list[AgeingResponse])
async def get_ageing(
    session: DbSession,
    supplier_id: uuid.UUID | None = Query(None),
    _user=Depends(require_permission("erp_rep.ageing.view")),
) -> list[AgeingResponse]:
    """AP ageing report — outstanding bills grouped by due-date bucket."""
    service = BillService(session)
    return await service.get_ageing(supplier_id=supplier_id)


# ---------------------------------------------------------------- debit notes


@router.post(
    "/debit-notes",
    response_model=DebitNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_debit_note(
    payload: DebitNoteCreateRequest,
    session: DbSession,
    _user=Depends(require_permission("erp_ap.debit_note.create")),
) -> DebitNoteResponse:
    """Create a draft debit note."""
    service = DebitNoteService(session)
    dn = await service.create(payload)
    await session.commit()
    return DebitNoteResponse.model_validate(dn)


@router.get("/debit-notes/{note_id}", response_model=DebitNoteResponse)
async def get_debit_note(
    note_id: uuid.UUID,
    session: DbSession,
    _user=Depends(require_permission("erp_ap.debit_note.create")),
) -> DebitNoteResponse:
    """Get a debit note by ID."""
    from app.modules.payables.repository import DebitNoteRepository

    repo = DebitNoteRepository(session)
    dn = await repo.get(note_id)
    if dn is None:
        raise HTTPException(status_code=404, detail="Debit note not found")
    return DebitNoteResponse.model_validate(dn)
