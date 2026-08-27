"""Finance↔Inventory bridge — event subscribers that auto-post journal entries.

Subscribes to inventory domain events and calls PostingService.post() with the
caller's session so the journal is written in the same transaction as the
inventory operation (atomic bridge).

Registered at app startup via ledger/__init__.py.

Event payload must include ``session`` — the caller's AsyncSession — so the
journal flushes in the same transaction as the inventory write.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.core.events import (
    FinanceEvents,
    InventoryEvents,
    subscribe_async,
)
from app.core.money import money, money_zero
from app.modules.ledger.posting import PostingService
from app.modules.ledger.schemas import JournalEntryCreateRequest, JournalLineRequest


def register_bridge_handlers() -> None:
    """Wire up all bridge subscribers. Called at app startup."""
    subscribe_async(InventoryEvents.GRN_CONFIRMED, _on_grn_confirmed)
    subscribe_async(InventoryEvents.UNIT_DISPATCHED, _on_unit_dispatched)
    subscribe_async(FinanceEvents.INVOICE_CREATED, _on_invoice_created)
    subscribe_async(InventoryEvents.ADJUSTMENT_CONFIRMED, _on_adjustment_confirmed)
    subscribe_async(FinanceEvents.BILL_MATCHED, _on_bill_matched)


async def _resolve_account_id(session, code: str) -> uuid.UUID:
    """Look up an account UUID by its code. Raises PostingError if missing."""
    from app.modules.ledger.repository import AccountRepository

    repo = AccountRepository(session)
    account = await repo.get_by_code(code)
    if account is None:
        from app.modules.ledger.posting import PostingError

        raise PostingError(
            f"Account code '{code}' not found in chart of accounts.",
            code="account_not_found",
        )
    return account.id


def _linereq(
    account_id: uuid.UUID,
    description: str,
    dr: Decimal | None = None,
    cr: Decimal | None = None,
    party_type: str | None = None,
    party_id: uuid.UUID | None = None,
) -> JournalLineRequest:
    """Build a balanced journal line request — one side only."""
    return JournalLineRequest(
        account_id=account_id,
        description=description,
        dr=dr if dr is not None else money_zero(),
        cr=cr if cr is not None else money_zero(),
        dr_base=dr if dr is not None else money_zero(),
        cr_base=cr if cr is not None else money_zero(),
        party_type=party_type,
        party_id=party_id,
    )


# --------------------------------------------------------- event handlers


async def _on_grn_confirmed(event_name: str, **payload) -> None:
    """Goods receipt: Dr Inventory 1200 / Cr GRN Accrual 2200."""
    session = payload.pop("session", None)
    if session is None:
        return
    grn_id = payload.get("grn_id")
    amt = money(payload.get("total_value", "0"))
    inv_acct = await _resolve_account_id(session, "1200")
    grn_acct = await _resolve_account_id(session, "2200")

    req = JournalEntryCreateRequest(
        posting_date=payload.get("posting_date", date.today()),
        description=f"Goods receipt GRN #{payload.get('grn_no', grn_id)}",
        voucher_type="journal_entry",
        lines=[
            _linereq(inv_acct, "Inventory receipt", dr=amt),
            _linereq(grn_acct, "GRN accrual", cr=amt),
        ],
    )
    await PostingService(session).post(
        req, actor_id=payload.get("actor_id"),
        source_type="grn", source_id=grn_id, is_system_generated=True,
    )


async def _on_unit_dispatched(event_name: str, **payload) -> None:
    """Goods dispatched: Dr COGS 5100 / Cr Inventory 1200."""
    session = payload.pop("session", None)
    if session is None:
        return
    dispatch_id = payload.get("dispatch_id")
    amt = money(payload.get("cogs_total", "0"))
    cogs = await _resolve_account_id(session, "5100")
    inv = await _resolve_account_id(session, "1200")

    req = JournalEntryCreateRequest(
        posting_date=payload.get("posting_date", date.today()),
        description=f"COGS for dispatch #{payload.get('dispatch_no', dispatch_id)}",
        voucher_type="journal_entry",
        lines=[
            _linereq(cogs, "Cost of goods sold", dr=amt),
            _linereq(inv, "Inventory relief", cr=amt),
        ],
    )
    await PostingService(session).post(
        req, actor_id=payload.get("actor_id"),
        source_type="dispatch", source_id=dispatch_id, is_system_generated=True,
    )


async def _on_invoice_created(event_name: str, **payload) -> None:
    """Sales invoice issued: Dr AR 1100 / Cr Revenue 4100."""
    session = payload.pop("session", None)
    if session is None:
        return
    invoice_id = payload.get("invoice_id")
    amt = money(payload.get("total", "0"))
    ar = await _resolve_account_id(session, "1100")
    rev = await _resolve_account_id(session, "4100")

    req = JournalEntryCreateRequest(
        posting_date=payload.get("posting_date", date.today()),
        description=f"Sales invoice #{payload.get('invoice_no', invoice_id)}",
        voucher_type="journal_entry",
        lines=[
            _linereq(ar, "Accounts receivable", dr=amt,
                     party_type="customer", party_id=payload.get("customer_id")),
            _linereq(rev, "Sales revenue", cr=amt),
        ],
    )
    await PostingService(session).post(
        req, actor_id=payload.get("actor_id"),
        source_type="sales_invoice", source_id=invoice_id, is_system_generated=True,
    )


async def _on_adjustment_confirmed(event_name: str, **payload) -> None:
    """Stock adjustment: Dr Write-Off 5200 / Cr Inventory 1200 (or reverse)."""
    session = payload.pop("session", None)
    if session is None:
        return
    adj_id = payload.get("adjustment_id")
    amt = money(payload.get("amount", "0"))
    inv = await _resolve_account_id(session, "1200")

    if amt < 0:
        lines = [
            _linereq(inv, "Stock adjustment — gain", dr=abs(amt)),
            _linereq(await _resolve_account_id(session, "4200"), "Adjustment income", cr=abs(amt)),
        ]
    else:
        lines = [
            _linereq(await _resolve_account_id(session, "5200"), "Stock write-off", dr=amt),
            _linereq(inv, "Inventory relief", cr=amt),
        ]

    req = JournalEntryCreateRequest(
        posting_date=payload.get("posting_date", date.today()),
        description=f"Stock adjustment #{payload.get('adjustment_no', adj_id)}",
        voucher_type="journal_entry",
        lines=lines,
    )
    await PostingService(session).post(
        req, actor_id=payload.get("actor_id"),
        source_type="stock_adjustment", source_id=adj_id, is_system_generated=True,
    )


async def _on_bill_matched(event_name: str, **payload) -> None:
    """Supplier bill matched: Dr GRN Accrual 2200 / Cr AP 2100."""
    session = payload.pop("session", None)
    if session is None:
        return
    bill_id = payload.get("bill_id")
    amt = money(payload.get("matched_amount", "0"))
    grn_acc = await _resolve_account_id(session, "2200")
    ap = await _resolve_account_id(session, "2100")

    req = JournalEntryCreateRequest(
        posting_date=payload.get("posting_date", date.today()),
        description=f"Bill #{payload.get('bill_no', bill_id)} matched to GRN",
        voucher_type="journal_entry",
        lines=[
            _linereq(grn_acc, "Clear GRN accrual", dr=amt),
            _linereq(ap, "Accounts payable", cr=amt,
                     party_type="supplier", party_id=payload.get("supplier_id")),
        ],
    )
    await PostingService(session).post(
        req, actor_id=payload.get("actor_id"),
        source_type="supplier_bill", source_id=bill_id, is_system_generated=True,
    )
