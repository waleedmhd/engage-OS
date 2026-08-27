"""Receivables service — invoice/payment/credit-note business logic.

Pattern: takes an AsyncSession, builds its own repositories, flushes writes.
Routers commit. The caller provides actor_id for audit context.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import FinanceEvents, emit_event_async
from app.core.exceptions import ConflictError, NotFoundError
from app.core.money import money, money_zero, money_sum
from app.modules.receivables.constants import (
    AGEING_BUCKETS,
    CreditNoteStatus,
    InvoiceStatus,
    PaymentStatus,
)
from app.modules.receivables.models import (
    CreditNote,
    CustomerPayment,
    PaymentAllocation,
    SalesInvoice,
    SalesInvoiceLine,
)
from app.modules.receivables.repository import (
    CreditNoteRepository,
    CustomerPaymentRepository,
    PaymentAllocationRepository,
    SalesInvoiceLineRepository,
    SalesInvoiceRepository,
)
from app.modules.receivables.schemas import (
    InvoiceLineResponse,
    AgeingBucket,
    AgeingResponse,
    AllocationResponse,
    ContactErpSummary,
    CreditNoteCreateRequest,
    CreditNoteResponse,
    InvoiceCreateRequest,
    InvoiceLineRequest,
    InvoiceResponse,
    PaymentAllocationRequest,
    PaymentCreateRequest,
    PaymentResponse,
)


def _invoice_response(invoice: SalesInvoice) -> InvoiceResponse:
    """Build an InvoiceResponse including computed line responses."""
    return InvoiceResponse(
        id=invoice.id,
        invoice_no=invoice.invoice_no,
        customer_id=invoice.customer_id,
        posting_date=invoice.posting_date,
        due_date=invoice.due_date,
        currency_code=invoice.currency_code,
        fx_rate=invoice.fx_rate,
        subtotal=invoice.subtotal,
        tax_total=invoice.tax_total,
        total=invoice.total,
        status=invoice.status,
        je_id=invoice.je_id,
        remarks=invoice.remarks,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
        lines=[InvoiceLineResponse.model_validate(line) for line in invoice.lines],
    )


def _compute_line(line: InvoiceLineRequest) -> tuple[Decimal, Decimal, Decimal]:
    """Return (line_total, tax_amount, line_total_with_tax) for a single line."""
    qty = line.qty
    unit_price = line.unit_price
    line_total = money(qty * unit_price)
    tax_amount = money(line_total * line.tax_rate)
    return line_total, tax_amount, money(line_total + tax_amount)


# ===================================================================== InvoiceService


class InvoiceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SalesInvoiceRepository(session)
        self._line_repo = SalesInvoiceLineRepository(session)

    # --------------------------------------------------------------------- reads

    async def get(self, invoice_id: uuid.UUID) -> SalesInvoice:
        invoice = await self._repo.get_with_lines(invoice_id)
        if invoice is None:
            raise NotFoundError(f"SalesInvoice {invoice_id} not found")
        return invoice

    async def list_invoices(
        self,
        *,
        customer_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SalesInvoice]:
        return await self._repo.list_paginated(
            customer_id=customer_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    # -------------------------------------------------------------------- writes

    async def create(self, request: InvoiceCreateRequest) -> SalesInvoice:
        """Create a draft invoice with lines. Computes line totals, subtotal, tax_total, total."""
        # Validate customer exists.
        from app.modules.contacts.models import Contact

        customer = await self._session.get(Contact, request.customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {request.customer_id} not found")

        invoice_no = await self._repo.generate_invoice_no()

        # Compute totals from lines.
        subtotal = money_zero()
        tax_total = money_zero()
        total = money_zero()

        invoice = await self._repo.create(
            invoice_no=invoice_no,
            customer_id=request.customer_id,
            posting_date=request.posting_date,
            due_date=request.due_date,
            currency_code=request.currency_code,
            fx_rate=Decimal("1"),
            subtotal=money_zero(),
            tax_total=money_zero(),
            total=money_zero(),
            status=InvoiceStatus.DRAFT.value,
            remarks=request.remarks,
        )

        for line_req in request.lines:
            line_total, tax_amount, line_gross = _compute_line(line_req)
            subtotal += line_total
            tax_total += tax_amount
            total += line_gross

            await self._line_repo.create(
                invoice_id=invoice.id,
                item_id=line_req.item_id,
                description=line_req.description or "",
                qty=line_req.qty,
                unit_price=line_req.unit_price,
                line_total=line_total,
                tax_code_id=line_req.tax_code_id,
                tax_rate=line_req.tax_rate,
                tax_amount=tax_amount,
            )

        # Update header totals.
        await self._repo.update(
            invoice.id,
            subtotal=money(subtotal),
            tax_total=money(tax_total),
            total=money(total),
        )

        
        return await self._repo.get_with_lines(invoice.id)  # type: ignore[return-value]

    async def issue(self, invoice_id: uuid.UUID, actor_id: uuid.UUID) -> SalesInvoice:
        """Issue a draft invoice: validate period open, post journal via event."""
        invoice = await self._repo.get_with_lines(invoice_id)
        if invoice is None:
            raise NotFoundError(f"SalesInvoice {invoice_id} not found")

        if invoice.status != InvoiceStatus.DRAFT.value:
            raise ConflictError(
                f"Cannot issue invoice in '{invoice.status}' status. Must be 'draft'.",
                details={"invoice_id": str(invoice_id), "status": invoice.status},
            )

        # Mark as issued.
        await self._repo.update(invoice.id, status=InvoiceStatus.ISSUED.value)
        await self._session.flush()

        # Fire the async event for journal posting. The ledger bridge handler
        # posts Dr AR / Cr Revenue in the same transaction if registered.
        # We await it so any bridge subscriber runs before the caller commits.
        await emit_event_async(
            FinanceEvents.INVOICE_CREATED,
            session=self._session,
            invoice_id=invoice.id,
            total=invoice.total,
            customer_id=invoice.customer_id,
            invoice_no=invoice.invoice_no,
            posting_date=invoice.posting_date,
            actor_id=actor_id,
        )

        # Re-load to pick up any je_id set by the bridge handler.
        await self._session.refresh(invoice)
        return await self._repo.get_with_lines(invoice.id)  # type: ignore[return-value]

    async def void(self, invoice_id: uuid.UUID, actor_id: uuid.UUID) -> SalesInvoice:
        """Void a draft or issued invoice. Reverses journal if posted."""
        invoice = await self._repo.get_with_lines(invoice_id)
        if invoice is None:
            raise NotFoundError(f"SalesInvoice {invoice_id} not found")

        if invoice.status not in (InvoiceStatus.DRAFT.value, InvoiceStatus.ISSUED.value):
            raise ConflictError(
                f"Cannot void invoice in '{invoice.status}' status.",
                details={"invoice_id": str(invoice_id), "status": invoice.status},
            )

        await self._repo.update(invoice.id, status=InvoiceStatus.VOID.value)

        # If there is a journal entry posted, fire a reversal event.
        if invoice.je_id is not None:
            await emit_event_async(
                "finance.invoice_voided",
                session=self._session,
                invoice_id=invoice.id,
                je_id=invoice.je_id,
                total=invoice.total,
                actor_id=actor_id,
            )

        await self._session.flush()
        await self._session.refresh(invoice)
        
        invoice = await self._repo.get_with_lines(invoice.id)
        if invoice is None:
            raise NotFoundError(f"Invoice {invoice_id} not found")
        return invoice

    # ------------------------------------------------------------------- ageing

    async def get_ageing(self, customer_id: uuid.UUID | None = None) -> AgeingResponse:
        """Compute ageing report — buckets of outstanding invoices by days overdue."""
        today = date.today()
        outstanding = await self._repo.list_outstanding(customer_id=customer_id)
        total_outstanding = await self._repo.sum_outstanding(customer_id=customer_id)

        buckets: list[AgeingBucket] = []
        for label, min_days, max_days in AGEING_BUCKETS:
            bucket_invoices: list[SalesInvoice] = []
            for inv in outstanding:
                days_overdue = (today - inv.due_date).days
                if max_days is None:
                    if days_overdue >= min_days:
                        bucket_invoices.append(inv)
                else:
                    if min_days <= days_overdue <= max_days:
                        bucket_invoices.append(inv)

            bucket_total = money_sum(inv.total for inv in bucket_invoices)
            buckets.append(
                AgeingBucket(
                    label=label,
                    count=len(bucket_invoices),
                    total=bucket_total,
                )
            )

        customer_name: str | None = None
        if customer_id is not None:
            from app.modules.contacts.models import Contact

            contact = await self._session.get(Contact, customer_id)
            if contact is not None:
                customer_name = contact.name

        return AgeingResponse(
            customer_id=customer_id,
            customer_name=customer_name,
            buckets=buckets,
            total_outstanding=money(total_outstanding),
        )


# ===================================================================== PaymentService


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CustomerPaymentRepository(session)
        self._alloc_repo = PaymentAllocationRepository(session)
        self._invoice_repo = SalesInvoiceRepository(session)

    # --------------------------------------------------------------------- reads

    async def get(self, payment_id: uuid.UUID) -> CustomerPayment:
        payment = await self._repo.get(payment_id)
        if payment is None:
            raise NotFoundError(f"CustomerPayment {payment_id} not found")
        return payment

    async def list_payments(
        self,
        *,
        customer_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CustomerPayment]:
        if customer_id is not None:
            return await self._repo.list_by_customer(customer_id, limit=limit, offset=offset)
        result = await self._repo.list(limit=limit, offset=offset)
        return list(result)

    # -------------------------------------------------------------------- writes

    async def create(self, request: PaymentCreateRequest) -> CustomerPayment:
        """Record a customer payment."""
        # Validate customer exists.
        from app.modules.contacts.models import Contact

        customer = await self._session.get(Contact, request.customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {request.customer_id} not found")

        # Validate payment method against PaymentMethod enum values.
        from app.modules.receivables.constants import PaymentMethod as PMEnum

        valid_methods = {e.value for e in PMEnum}
        if request.payment_method not in valid_methods:
            raise ValueError(f"payment_method must be one of {sorted(valid_methods)}")

        payment_no = await self._repo.generate_payment_no()

        payment = await self._repo.create(
            payment_no=payment_no,
            customer_id=request.customer_id,
            payment_date=request.payment_date,
            amount=money(request.amount),
            currency_code=request.currency_code,
            fx_rate=Decimal("1"),
            payment_method=request.payment_method,
            reference=request.reference,
            status=PaymentStatus.UNCLEARED.value,
        )
        return payment

    async def allocate(
        self, payment_id: uuid.UUID, allocations: list[PaymentAllocationRequest]
    ) -> list[PaymentAllocation]:
        """Allocate a payment to one or more invoices. Validates amounts and constraints."""
        payment = await self._repo.get(payment_id)
        if payment is None:
            raise NotFoundError(f"CustomerPayment {payment_id} not found")

        if payment.status == PaymentStatus.VOID.value:
            raise ConflictError(
                "Cannot allocate a voided payment.",
                details={"payment_id": str(payment_id)},
            )

        result: list[PaymentAllocation] = []
        total_allocated = await self._alloc_repo.sum_allocated_for_payment(payment_id)

        for alloc_req in allocations:
            new_total = total_allocated + alloc_req.amount
            if new_total > payment.amount:
                raise ConflictError(
                    f"Total allocations ({new_total}) exceed payment amount ({payment.amount}).",
                    details={
                        "payment_id": str(payment_id),
                        "payment_amount": str(payment.amount),
                        "attempted_total": str(new_total),
                    },
                )

            # Validate invoice exists and is in an allocatable state.
            invoice = await self._invoice_repo.get(alloc_req.invoice_id)
            if invoice is None:
                raise NotFoundError(f"SalesInvoice {alloc_req.invoice_id} not found")

            if invoice.status not in (InvoiceStatus.ISSUED.value, InvoiceStatus.OVERDUE.value, InvoiceStatus.PAID.value):
                raise ConflictError(
                    f"Cannot allocate payment to invoice in '{invoice.status}' status.",
                    details={"invoice_id": str(alloc_req.invoice_id)},
                )

            allocation = await self._alloc_repo.create(
                payment_id=payment_id,
                invoice_id=alloc_req.invoice_id,
                amount=money(alloc_req.amount),
            )
            result.append(allocation)
            total_allocated += alloc_req.amount

            # Check if invoice is now fully paid.
            allocated_for_invoice = await self._alloc_repo.sum_allocated(alloc_req.invoice_id)
            if allocated_for_invoice >= invoice.total:
                await self._invoice_repo.update(invoice.id, status=InvoiceStatus.PAID.value)

        # Update payment status.
        allocated_all = await self._alloc_repo.sum_allocated_for_payment(payment_id)
        if allocated_all >= payment.amount:
            await self._repo.update(payment.id, status=PaymentStatus.CLEARED.value)

        return result

    async def reconcile(
        self, payment_id: uuid.UUID, actor_id: uuid.UUID
    ) -> CustomerPayment:
        """Post the payment journal entry (Dr Bank / Cr AR)."""
        payment = await self._repo.get(payment_id)
        if payment is None:
            raise NotFoundError(f"CustomerPayment {payment_id} not found")

        if payment.status != PaymentStatus.UNCLEARED.value:
            raise ConflictError(
                f"Cannot reconcile payment in '{payment.status}' status.",
                details={"payment_id": str(payment_id)},
            )

        await emit_event_async(
            "finance.payment_reconciled",
            session=self._session,
            payment_id=payment.id,
            amount=payment.amount,
            customer_id=payment.customer_id,
            payment_no=payment.payment_no,
            payment_date=payment.payment_date,
            payment_method=payment.payment_method,
            actor_id=actor_id,
        )

        # Mark as cleared after reconcile.
        await self._repo.update(payment.id, status=PaymentStatus.CLEARED.value)
        await self._session.refresh(payment)
        return payment


# ===================================================================== CreditNoteService


class CreditNoteService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CreditNoteRepository(session)

    # --------------------------------------------------------------------- reads

    async def get(self, note_id: uuid.UUID) -> CreditNote:
        note = await self._repo.get(note_id)
        if note is None:
            raise NotFoundError(f"CreditNote {note_id} not found")
        return note

    # -------------------------------------------------------------------- writes

    async def create(self, request: CreditNoteCreateRequest) -> CreditNote:
        """Create a draft credit note."""
        from app.modules.contacts.models import Contact

        customer = await self._session.get(Contact, request.customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {request.customer_id} not found")

        if request.invoice_id is not None:
            invoice = await self._session.get(SalesInvoice, request.invoice_id)
            if invoice is None:
                raise NotFoundError(f"SalesInvoice {request.invoice_id} not found")
            if invoice.customer_id != request.customer_id:
                raise ConflictError(
                    "Credit note invoice does not belong to the specified customer.",
                    details={
                        "customer_id": str(request.customer_id),
                        "invoice_id": str(request.invoice_id),
                        "invoice_customer_id": str(invoice.customer_id),
                    },
                )

        credit_note_no = await self._repo.generate_credit_note_no()

        return await self._repo.create(
            credit_note_no=credit_note_no,
            customer_id=request.customer_id,
            invoice_id=request.invoice_id,
            date=request.date,
            amount=money(request.amount),
            reason=request.reason,
            currency_code=request.currency_code,
            fx_rate=Decimal("1"),
            status=CreditNoteStatus.DRAFT.value,
            remarks=request.remarks,
        )

    async def issue(self, note_id: uuid.UUID, actor_id: uuid.UUID) -> CreditNote:
        """Issue a draft credit note: post the reversing journal."""
        note = await self._repo.get(note_id)
        if note is None:
            raise NotFoundError(f"CreditNote {note_id} not found")

        if note.status != CreditNoteStatus.DRAFT.value:
            raise ConflictError(
                f"Cannot issue credit note in '{note.status}' status.",
                details={"note_id": str(note_id)},
            )

        # Fire the event for journal posting.
        await emit_event_async(
            "finance.credit_note_issued",
            session=self._session,
            credit_note_id=note.id,
            amount=note.amount,
            customer_id=note.customer_id,
            credit_note_no=note.credit_note_no,
            date=note.date,
            invoice_id=note.invoice_id,
            actor_id=actor_id,
        )

        await self._repo.update(note.id, status=CreditNoteStatus.ISSUED.value)
        await self._session.refresh(note)
        return note


# ============================================================== Credit Control Helper


async def check_credit_limit(
    session: AsyncSession, customer_id: uuid.UUID, amount: Decimal
) -> bool:
    """Return True if the customer has sufficient available credit.

    Queries the contact's credit_limit (if set) against outstanding AR.
    If no credit limit is set, returns True (no limit).
    """
    from app.modules.contacts.models import Contact

    contact = await session.get(Contact, customer_id)
    if contact is None:
        raise NotFoundError(f"Customer {customer_id} not found")

    # If no credit limit is configured, no check is needed.
    credit_limit = getattr(contact, "credit_limit", None)
    if credit_limit is None or credit_limit <= 0:
        return True

    # Sum outstanding AR for this customer.
    invoice_repo = SalesInvoiceRepository(session)
    outstanding = await invoice_repo.sum_outstanding(customer_id=customer_id)

    # Also sum open credit notes (issued, not yet allocated) — these reduce AR.
    credit_note_stmt = (
        sa.select(sa.func.coalesce(sa.func.sum(CreditNote.amount), 0))
        .where(
            CreditNote.customer_id == customer_id,
            CreditNote.status == CreditNoteStatus.ISSUED.value,
        )
    )
    credit_note_result = await session.execute(credit_note_stmt)
    credit_notes_total = Decimal(str(credit_note_result.scalar_one()))

    net_ar = outstanding - credit_notes_total
    available = Decimal(str(credit_limit)) - net_ar

    return available >= amount


# ===================================================================== CRM Integration


async def get_contact_erp_summary(
    session: AsyncSession, contact_id: uuid.UUID
) -> ContactErpSummary:
    """Build the ERP summary for the CRM inbox sidebar."""
    invoice_repo = SalesInvoiceRepository(session)

    outstanding = await invoice_repo.sum_outstanding(customer_id=contact_id)
    last_invoices = await invoice_repo.list_by_customer(contact_id, limit=5, offset=0)

    # Total revenue: sum of all issued/paid/overdue invoice totals.
    revenue_stmt = sa.select(
        sa.func.coalesce(sa.func.sum(SalesInvoice.total), 0)
    ).where(
        SalesInvoice.customer_id == contact_id,
        SalesInvoice.status.in_([
            InvoiceStatus.ISSUED.value,
            InvoiceStatus.PAID.value,
            InvoiceStatus.OVERDUE.value,
        ]),
    )
    revenue_result = await session.execute(revenue_stmt)
    total_revenue = Decimal(str(revenue_result.scalar_one()))

    return ContactErpSummary(
        outstanding_ar_balance=money(outstanding),
        total_revenue=money(total_revenue),
        last_invoices=[InvoiceResponse.model_validate(inv) for inv in last_invoices],
    )
