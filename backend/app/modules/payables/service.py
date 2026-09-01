"""Payables service — bill creation, issuance, void; payment recording, allocation,
reconciliation; debit notes; ageing calculation.

Uses the async session throughout for the HTTP path. Celery tasks use
sync_session_factory() for the worker path.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import FinanceEvents, emit_event_async
from app.core.exceptions import NotFoundError, ValidationError
from app.core.money import money, money_zero
from app.modules.contacts.models import Contact
from app.modules.ledger.constants import JournalVoucherType
from app.modules.ledger.posting import PostingService
from app.modules.ledger.schemas import JournalEntryCreateRequest, JournalLineRequest
from app.modules.payables.constants import (
    AGEING_BUCKETS,
    BillStatus,
    DebitNoteStatus,
    PaymentStatus,
)
from app.modules.payables.models import (
    BillAllocation,
    DebitNote,
    SupplierBill,
    SupplierBillLine,
    SupplierPayment,
)
from app.modules.payables.repository import (
    BillAllocationRepository,
    DebitNoteRepository,
    SupplierBillLineRepository,
    SupplierBillRepository,
    SupplierPaymentRepository,
)
from app.modules.payables.schemas import (
    AgeingBucket,
    AgeingResponse,
    BillCreateRequest,
    DebitNoteCreateRequest,
    PaymentAllocationRequest,
    PaymentCreateRequest,
)


class BillService:
    """AP Bill lifecycle — create, issue, void, compute ageing."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._bill_repo = SupplierBillRepository(session)
        self._line_repo = SupplierBillLineRepository(session)
        self._alloc_repo = BillAllocationRepository(session)

    # ----------------------------------------------------------- bill CRUD

    async def create(
        self,
        request: BillCreateRequest,
    ) -> SupplierBill:
        """Create a draft bill. Validates supplier existence, calculates line totals."""

        # Validate supplier exists.
        supplier = await self._session.get(Contact, request.supplier_id)
        if supplier is None:
            raise ValidationError(
                f"Supplier {request.supplier_id} not found.",
                details={"code": "supplier_not_found"},
            )

        # Allocate bill number.
        bill_no = await _next_doc_number(self._session, "supplier_bill", "BIL")

        # Calculate line totals.
        lines_data = []
        subtotal = money_zero()
        tax_total = money_zero()
        for line_req in request.lines:
            line_total = money(line_req.qty * line_req.unit_cost)
            tax_amt = money_zero()  # tax computed in phase 2
            lines_data.append(
                {
                    "item_id": line_req.item_id,
                    "description": line_req.description,
                    "qty": line_req.qty,
                    "unit_cost": line_req.unit_cost,
                    "line_total": line_total,
                    "tax_code_id": None,
                    "tax_rate": Decimal("0"),
                    "tax_amount": tax_amt,
                }
            )
            subtotal += line_total
            tax_total += tax_amt

        total = subtotal + tax_total

        bill = await self._bill_repo.create(
            bill_no=bill_no,
            supplier_id=request.supplier_id,
            po_id=request.po_id,
            grn_id=request.grn_id,
            posting_date=request.posting_date,
            due_date=request.due_date,
            currency_code=request.currency_code,
            fx_rate=Decimal("1"),
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
            status=BillStatus.DRAFT.value,
            remarks=request.remarks,
        )

        for ld in lines_data:
            ld["bill_id"] = bill.id
            await self._line_repo.create(**ld)

        # Re-fetch with lines so response is complete.
        return await self._bill_repo.get_with_lines(bill.id)  # type: ignore[return-value]

    async def issue(self, bill_id: uuid.UUID, actor_id: uuid.UUID) -> SupplierBill:
        """Issue the bill and post the journal entry (Dr GRN Accrual 2200 / Cr AP 2100)."""
        bill = await self._bill_repo.get_with_lines(bill_id)
        if bill is None:
            raise NotFoundError(f"Bill {bill_id} not found")
        if bill.status != BillStatus.DRAFT.value:
            raise ValidationError(
                f"Only draft bills can be issued. Current status: {bill.status}",
                details={"code": "cannot_issue_non_draft"},
            )

        # Post journal: Dr 2200 GRN Accrual / Cr 2100 AP
        from app.modules.ledger.repository import AccountRepository

        acct_repo = AccountRepository(self._session)
        grn_accrual = await acct_repo.get_by_code("2200")
        ap_account = await acct_repo.get_by_code("2100")
        if grn_accrual is None or ap_account is None:
            raise ValidationError(
                "GRN Accrual (2200) or AP (2100) account not found in chart of accounts.",
                details={"code": "missing_control_accounts"},
            )

        lines = [
            JournalLineRequest(
                account_id=grn_accrual.id,
                description=f"Bill {bill.bill_no} — clear GRN accrual",
                dr=bill.total,
                cr=money_zero(),
                dr_base=bill.total,
                cr_base=money_zero(),
                party_type="supplier",
                party_id=bill.supplier_id,
            ),
            JournalLineRequest(
                account_id=ap_account.id,
                description=f"Bill {bill.bill_no} — accounts payable",
                dr=money_zero(),
                cr=bill.total,
                dr_base=money_zero(),
                cr_base=bill.total,
                party_type="supplier",
                party_id=bill.supplier_id,
            ),
        ]

        je_req = JournalEntryCreateRequest(
            posting_date=bill.posting_date,
            description=f"Supplier bill {bill.bill_no}",
            voucher_type=JournalVoucherType.JOURNAL_ENTRY.value,
            lines=lines,
        )

        posting = PostingService(self._session)
        entry = await posting.post(
            je_req,
            actor_id=actor_id,
            source_type="supplier_bill",
            source_id=bill.id,
            is_system_generated=True,
        )

        bill.status = BillStatus.ISSUED.value
        bill.je_id = entry.id
        await self._session.flush()

        await emit_event_async(
            FinanceEvents.BILL_MATCHED,
            session=self._session,
            bill_id=bill.id,
            bill_no=bill.bill_no,
            matched_amount=str(bill.total),
            posting_date=bill.posting_date,
            supplier_id=bill.supplier_id,
        )

        return await self._bill_repo.get_with_lines(bill.id)  # type: ignore[return-value]

    async def void(self, bill_id: uuid.UUID, actor_id: uuid.UUID) -> SupplierBill:
        """Void a bill — only if it has not been paid."""
        bill = await self._bill_repo.get_with_lines(bill_id)
        if bill is None:
            raise NotFoundError(f"Bill {bill_id} not found")
        if bill.status == BillStatus.PAID.value:
            raise ValidationError(
                "Cannot void a paid bill.", details={"code": "cannot_void_paid"}
            )
        if bill.status == BillStatus.VOID.value:
            raise ValidationError(
                "Bill is already voided.", details={"code": "already_voided"}
            )

        bill.status = BillStatus.VOID.value
        await self._session.flush()
        return await self._bill_repo.get_with_lines(bill.id)  # type: ignore[return-value]

    async def get_ageing(
        self,
        supplier_id: uuid.UUID | None = None,
    ) -> list[AgeingResponse]:
        """Compute AP ageing — group outstanding bills by due-date bucket.

        Returns a list of AgeingResponse, one per supplier if supplier_id is None,
        or a single element if supplier_id is provided.
        """
        outstanding = await self._bill_repo.list_outstanding(
            supplier_id=supplier_id, limit=10_000, offset=0
        )
        today = date.today()

        # Group bills by supplier.
        by_supplier: dict[uuid.UUID, dict] = {}
        for bill in outstanding:
            sid = bill.supplier_id
            if sid not in by_supplier:
                supplier = await self._session.get(Contact, sid)
                by_supplier[sid] = {
                    "supplier_name": supplier.name if supplier else str(sid),
                    "buckets": {label: [] for label, _, _ in AGEING_BUCKETS},
                }

            # Determine bucket.
            _, bucket_label = _compute_age_bucket(today, bill.due_date)
            by_supplier[sid]["buckets"][bucket_label].append(bill.total)

        results = []
        for sid, data in by_supplier.items():
            buckets = []
            total_outstanding = money_zero()
            for label, _low, _high in AGEING_BUCKETS:
                amounts = data["buckets"][label]
                count = len(amounts)
                total_amt = (
                    money_zero()
                    if count == 0
                    else sum(amounts, money_zero())
                )
                buckets.append(
                    AgeingBucket(label=label, count=count, total_amount=total_amt)
                )
                total_outstanding += total_amt

            results.append(
                AgeingResponse(
                    supplier_id=sid,
                    supplier_name=data["supplier_name"],
                    buckets=buckets,
                    total_outstanding=total_outstanding,
                )
            )

        return results


class PaymentService:
    """Supplier payment recording, allocation, and reconciliation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._payment_repo = SupplierPaymentRepository(session)
        self._alloc_repo = BillAllocationRepository(session)
        self._bill_repo = SupplierBillRepository(session)

    async def create(self, request: PaymentCreateRequest) -> SupplierPayment:
        """Record a payment against a supplier."""

        supplier = await self._session.get(Contact, request.supplier_id)
        if supplier is None:
            raise ValidationError(
                f"Supplier {request.supplier_id} not found.",
                details={"code": "supplier_not_found"},
            )

        payment_no = await _next_doc_number(self._session, "supplier_payment", "PAY")

        payment = await self._payment_repo.create(
            payment_no=payment_no,
            supplier_id=request.supplier_id,
            payment_date=request.payment_date,
            amount=request.amount,
            currency_code=request.currency_code,
            fx_rate=Decimal("1"),
            payment_method=request.payment_method,
            reference=request.reference,
            status=PaymentStatus.UNCLEARED.value,
        )
        return payment

    async def allocate(
        self, payment_id: uuid.UUID, request: PaymentAllocationRequest
    ) -> BillAllocation:
        """Allocate a portion (or all) of a payment to a specific bill."""
        payment = await self._payment_repo.get(payment_id)
        if payment is None:
            raise NotFoundError(f"Payment {payment_id} not found")
        if payment.status == PaymentStatus.VOID.value:
            raise ValidationError(
                "Cannot allocate to a voided payment.", details={"code": "payment_voided"}
            )

        bill = await self._bill_repo.get(request.bill_id)
        if bill is None:
            raise NotFoundError(f"Bill {request.bill_id} not found")
        if bill.supplier_id != payment.supplier_id:
            raise ValidationError(
                "Bill and payment must belong to the same supplier.",
                details={"code": "supplier_mismatch"},
            )
        if bill.status not in (BillStatus.ISSUED.value, BillStatus.OVERDUE.value):
            raise ValidationError(
                f"Cannot allocate to a bill with status '{bill.status}'.",
                details={"code": "bill_not_issuable"},
            )

        # Check over-allocation.
        already_allocated = await self._alloc_repo.sum_allocated(bill.id)
        remaining = bill.total - already_allocated
        if request.amount > remaining:
            raise ValidationError(
                f"Allocation amount {request.amount} exceeds remaining "
                f"balance {remaining} on bill {bill.bill_no}.",
                details={"code": "over_allocation"},
            )

        allocation = await self._alloc_repo.create(
            payment_id=payment_id,
            bill_id=request.bill_id,
            amount=request.amount,
        )

        # Check if bill is now fully paid.
        new_allocated = already_allocated + request.amount
        if new_allocated >= bill.total:
            bill.status = BillStatus.PAID.value

        await self._session.flush()
        return allocation

    async def reconcile(
        self, payment_id: uuid.UUID, actor_id: uuid.UUID
    ) -> SupplierPayment:
        """Reconcile a payment: posts Dr AP 2100 / Cr Bank 1020, marks payment cleared."""
        payment = await self._payment_repo.get_with_allocations(payment_id)
        if payment is None:
            raise NotFoundError(f"Payment {payment_id} not found")
        if payment.status == PaymentStatus.CLEARED.value:
            raise ValidationError(
                "Payment is already cleared.", details={"code": "already_cleared"}
            )
        if payment.status == PaymentStatus.VOID.value:
            raise ValidationError(
                "Cannot reconcile a voided payment.", details={"code": "payment_voided"}
            )

        from app.modules.ledger.repository import AccountRepository

        acct_repo = AccountRepository(self._session)
        ap_acct = await acct_repo.get_by_code("2100")
        bank_acct = await acct_repo.get_by_code("1020")
        if ap_acct is None or bank_acct is None:
            raise ValidationError(
                "AP (2100) or Bank (1020) account not found.",
                details={"code": "missing_control_accounts"},
            )

        lines = [
            JournalLineRequest(
                account_id=ap_acct.id,
                description=f"Payment {payment.payment_no} — clear AP",
                dr=payment.amount,
                cr=money_zero(),
                dr_base=payment.amount,
                cr_base=money_zero(),
                party_type="supplier",
                party_id=payment.supplier_id,
            ),
            JournalLineRequest(
                account_id=bank_acct.id,
                description=f"Payment {payment.payment_no} — bank credit",
                dr=money_zero(),
                cr=payment.amount,
                dr_base=money_zero(),
                cr_base=payment.amount,
            ),
        ]

        je_req = JournalEntryCreateRequest(
            posting_date=payment.payment_date,
            description=f"Supplier payment {payment.payment_no}",
            voucher_type=JournalVoucherType.BANK_ENTRY.value,
            lines=lines,
        )

        posting = PostingService(self._session)
        entry = await posting.post(
            je_req,
            actor_id=actor_id,
            source_type="supplier_payment",
            source_id=payment.id,
            is_system_generated=True,
        )

        payment.status = PaymentStatus.CLEARED.value
        payment.je_id = entry.id
        await self._session.flush()
        return payment


class DebitNoteService:
    """Debit note lifecycle — create, issue."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._dn_repo = DebitNoteRepository(session)

    async def create(self, request: DebitNoteCreateRequest) -> DebitNote:
        """Create a draft debit note."""

        supplier = await self._session.get(Contact, request.supplier_id)
        if supplier is None:
            raise ValidationError(
                f"Supplier {request.supplier_id} not found.",
                details={"code": "supplier_not_found"},
            )

        # Optional bill link validation.
        if request.bill_id is not None:
            bill_repo = SupplierBillRepository(self._session)
            bill = await bill_repo.get(request.bill_id)
            if bill is None:
                raise NotFoundError(f"Bill {request.bill_id} not found")
            if bill.supplier_id != request.supplier_id:
                raise ValidationError(
                    "Debit note bill must belong to the same supplier.",
                    details={"code": "supplier_mismatch"},
                )

        dn_no = await _next_doc_number(self._session, "debit_note", "DBN")

        dn = await self._dn_repo.create(
            debit_note_no=dn_no,
            supplier_id=request.supplier_id,
            bill_id=request.bill_id,
            date=request.date,
            amount=request.amount,
            reason=request.reason,
            currency_code=request.currency_code,
            fx_rate=Decimal("1"),
            status=DebitNoteStatus.DRAFT.value,
        )
        return dn

    async def issue(self, note_id: uuid.UUID, actor_id: uuid.UUID) -> DebitNote:
        """Issue a debit note and post journal: Dr AP 2100 / Cr Other Revenue 4200."""
        dn = await self._dn_repo.get(note_id)
        if dn is None:
            raise NotFoundError(f"Debit note {note_id} not found")
        if dn.status != DebitNoteStatus.DRAFT.value:
            raise ValidationError(
                f"Only draft debit notes can be issued. Current status: {dn.status}",
                details={"code": "cannot_issue_non_draft"},
            )

        from app.modules.ledger.repository import AccountRepository

        acct_repo = AccountRepository(self._session)
        ap_acct = await acct_repo.get_by_code("2100")
        rev_acct = await acct_repo.get_by_code("4200")
        if ap_acct is None or rev_acct is None:
            raise ValidationError(
                "AP (2100) or Other Revenue (4200) account not found.",
                details={"code": "missing_control_accounts"},
            )

        lines = [
            JournalLineRequest(
                account_id=ap_acct.id,
                description=f"Debit note {dn.debit_note_no} — reduce AP",
                dr=dn.amount,
                cr=money_zero(),
                dr_base=dn.amount,
                cr_base=money_zero(),
                party_type="supplier",
                party_id=dn.supplier_id,
            ),
            JournalLineRequest(
                account_id=rev_acct.id,
                description=f"Debit note {dn.debit_note_no} — other revenue",
                dr=money_zero(),
                cr=dn.amount,
                dr_base=money_zero(),
                cr_base=dn.amount,
            ),
        ]

        je_req = JournalEntryCreateRequest(
            posting_date=dn.date,
            description=f"Debit note {dn.debit_note_no}",
            voucher_type=JournalVoucherType.DEBIT_NOTE.value,
            lines=lines,
        )

        posting = PostingService(self._session)
        entry = await posting.post(
            je_req,
            actor_id=actor_id,
            source_type="debit_note",
            source_id=dn.id,
            is_system_generated=True,
        )

        dn.status = DebitNoteStatus.ISSUED.value
        dn.je_id = entry.id
        await self._session.flush()
        return dn


# --------------------------------------------------------------- helpers


def _compute_age_bucket(today: date, due_date: date) -> tuple[int, str]:
    """Return (days_overdue, bucket_label) for a given due_date."""
    days_overdue = (today - due_date).days
    if days_overdue <= 0:
        return days_overdue, "current"
    elif days_overdue <= 30:
        return days_overdue, "1_30"
    elif days_overdue <= 60:
        return days_overdue, "31_60"
    elif days_overdue <= 90:
        return days_overdue, "61_90"
    else:
        return days_overdue, "over_90"


_NUMBER_SEQUENCE_LOCK_SQL = (
    "SELECT next_value FROM number_sequences "
    "WHERE doc_type = :doc_type AND fiscal_year = :fy "
    "FOR UPDATE"
)


async def _next_doc_number(
    session: AsyncSession, doc_type: str, prefix: str
) -> str:
    """Allocate the next gapless document number for *doc_type*.

    Uses SELECT ... FOR UPDATE row lock on number_sequences.
    """
    from datetime import date as date_type

    import sqlalchemy as sa

    today = date_type.today()
    fiscal_year = today.year

    result = await session.execute(
        sa.text(_NUMBER_SEQUENCE_LOCK_SQL),
        {"doc_type": doc_type, "fy": fiscal_year},
    )
    row = result.one_or_none()

    if row is None:
        next_val = 1
        await session.execute(
            sa.text(
                "INSERT INTO number_sequences (doc_type, fiscal_year, next_value) "
                "VALUES (:doc_type, :fy, :next_val)"
            ),
            {"doc_type": doc_type, "fy": fiscal_year, "next_val": 2},
        )
    else:
        next_val = row[0]
        await session.execute(
            sa.text(
                "UPDATE number_sequences SET next_value = :next_val "
                "WHERE doc_type = :doc_type AND fiscal_year = :fy"
            ),
            {"next_val": next_val + 1, "doc_type": doc_type, "fy": fiscal_year},
        )

    return f"{prefix}-{fiscal_year}-{next_val:05d}"
