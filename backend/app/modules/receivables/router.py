"""Receivables (AR) endpoints.

Router commits after each mutating operation — same pattern as contacts and conversations.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDB, DbSession
from app.core.dependencies import require_permission
from app.modules.receivables.schemas import (
    AgeingResponse,
    AllocationResponse,
    ContactErpSummary,
    CreditNoteCreateRequest,
    CreditNoteResponse,
    InvoiceCreateRequest,
    InvoiceResponse,
    PaymentAllocationRequest,
    PaymentCreateRequest,
    PaymentResponse,
)
from app.modules.receivables.service import (
    CreditNoteService,
    InvoiceService,
    PaymentService,
    get_contact_erp_summary,
)

_PC = "erp_ar"

router = APIRouter(prefix="/receivables", tags=["receivables"])

# ----------------------------------------------------------------------- Invoices


@router.post(
    "/invoices",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice(
    payload: InvoiceCreateRequest,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.invoice.create")),
) -> InvoiceResponse:
    """Create a draft invoice with line items."""
    service = InvoiceService(session)
    invoice = await service.create(payload)
    await session.commit()
    return InvoiceResponse.model_validate(invoice)


@router.post(
    "/invoices/{invoice_id}/issue",
    response_model=InvoiceResponse,
)
async def issue_invoice(
    invoice_id: uuid.UUID,
    session: DbSession,
    user=Depends(require_permission(f"{_PC}.invoice.create")),
) -> InvoiceResponse:
    """Issue a draft invoice and post the AR journal."""
    service = InvoiceService(session)
    invoice = await service.issue(invoice_id, user.id)
    await session.commit()
    return InvoiceResponse.model_validate(invoice)


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceResponse,
)
async def get_invoice(
    invoice_id: uuid.UUID,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.invoice.read")),
) -> InvoiceResponse:
    """Get an invoice with its lines."""
    service = InvoiceService(session)
    invoice = await service.get(invoice_id)
    return InvoiceResponse.model_validate(invoice)


@router.get(
    "/invoices",
    response_model=list[InvoiceResponse],
)
async def list_invoices(
    session: DbSession,
    customer_id: uuid.UUID | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_permission(f"{_PC}.invoice.read")),
) -> list[InvoiceResponse]:
    """List invoices, optionally filtered by customer and/or status."""
    service = InvoiceService(session)
    invoices = await service.list_invoices(
        customer_id=customer_id,
        status=status_value,
        limit=limit,
        offset=offset,
    )
    return [InvoiceResponse.model_validate(inv) for inv in invoices]


@router.post(
    "/invoices/{invoice_id}/void",
    response_model=InvoiceResponse,
)
async def void_invoice(
    invoice_id: uuid.UUID,
    session: DbSession,
    user=Depends(require_permission(f"{_PC}.invoice.void")),
) -> InvoiceResponse:
    """Void an invoice (draft or issued only)."""
    service = InvoiceService(session)
    invoice = await service.void(invoice_id, user.id)
    await session.commit()
    return InvoiceResponse.model_validate(invoice)


# ----------------------------------------------------------------------- Payments


@router.post(
    "/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    payload: PaymentCreateRequest,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.payment.create")),
) -> PaymentResponse:
    """Record a customer payment."""
    service = PaymentService(session)
    payment = await service.create(payload)
    await session.commit()
    return PaymentResponse.model_validate(payment)


@router.post(
    "/payments/{payment_id}/allocate",
    response_model=list[AllocationResponse],
)
async def allocate_payment(
    payment_id: uuid.UUID,
    payload: list[PaymentAllocationRequest],
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.payment.allocate")),
) -> list[AllocationResponse]:
    """Allocate a payment to one or more invoices."""
    service = PaymentService(session)
    allocations = await service.allocate(payment_id, payload)
    await session.commit()
    return [AllocationResponse.model_validate(a) for a in allocations]


@router.get(
    "/payments",
    response_model=list[PaymentResponse],
)
async def list_payments(
    session: DbSession,
    customer_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_permission(f"{_PC}.payment.read")),
) -> list[PaymentResponse]:
    """List payments, optionally filtered by customer."""
    service = PaymentService(session)
    payments = await service.list_payments(
        customer_id=customer_id,
        limit=limit,
        offset=offset,
    )
    return [PaymentResponse.model_validate(p) for p in payments]


# ----------------------------------------------------------------------- Ageing


@router.get(
    "/ageing",
    response_model=AgeingResponse,
)
async def get_ageing(
    session: DbSession,
    customer_id: uuid.UUID | None = Query(default=None),
    _user=Depends(require_permission("erp_rep.ageing.view")),
) -> AgeingResponse:
    """Ageing report — outstanding invoices grouped by days overdue."""
    service = InvoiceService(session)
    return await service.get_ageing(customer_id=customer_id)


# ------------------------------------------------------------------- Credit Notes


@router.post(
    "/credit-notes",
    response_model=CreditNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_credit_note(
    payload: CreditNoteCreateRequest,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.credit_note.create")),
) -> CreditNoteResponse:
    """Create a draft credit note."""
    service = CreditNoteService(session)
    note = await service.create(payload)
    await session.commit()
    return CreditNoteResponse.model_validate(note)


@router.get(
    "/credit-notes/{note_id}",
    response_model=CreditNoteResponse,
)
async def get_credit_note(
    note_id: uuid.UUID,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.credit_note.read")),
) -> CreditNoteResponse:
    """Get a credit note by ID."""
    service = CreditNoteService(session)
    note = await service.get(note_id)
    return CreditNoteResponse.model_validate(note)


# ------------------------------------------------------------ CRM Inbox Integration


@router.get(
    "/contacts/{contact_id}/erp-summary",
    response_model=ContactErpSummary,
)
async def contact_erp_summary(
    contact_id: uuid.UUID,
    session: DbSession,
    _user=Depends(require_permission(f"{_PC}.invoice.read")),
) -> ContactErpSummary:
    """CRM inbox sidebar: outstanding AR balance, last 5 invoices, total revenue."""
    return await get_contact_erp_summary(session, contact_id)
