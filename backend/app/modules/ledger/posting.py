"""PostingService — single choke point for all journal creation.

Every journal entry (manual, bridge, reversal) passes through here. Validates:
- Period is open
- Control accounts aren't manually posted
- Total base-currency debits = total base-currency credits

Called by ledger router (manual journals) AND by bridge subscribers (auto-posted
entries from procurement/fulfilment/inventory). All on the caller's session so
bridge transactions are atomic.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import emit_event
from app.core.exceptions import ValidationError
from app.core.money import money_zero, money_sum
from app.modules.ledger.constants import (
    CONTROL_ACCOUNT_TYPES,
    JournalStatus,
    PeriodStatus,
)
from app.modules.ledger.models import JournalEntry, JournalLine
from app.modules.ledger.repository import (
    AccountRepository,
    FiscalPeriodRepository,
    JournalEntryRepository,
)
from app.modules.ledger.schemas import JournalEntryCreateRequest, JournalLineRequest


class PostingError(ValidationError):
    """Raised when a journal cannot be posted (unbalanced, closed period, control-account violation)."""

    def __init__(self, message: str, code: str = "posting_error") -> None:
        super().__init__(message, details={"code": code})


class PostingService:
    """Validate and post journal entries to the general ledger."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._account_repo = AccountRepository(session)
        self._period_repo = FiscalPeriodRepository(session)
        self._entry_repo = JournalEntryRepository(session)

    # ----------------------------------------------------------- public API

    async def post(
        self,
        request: JournalEntryCreateRequest,
        *,
        actor_id: uuid.UUID | None = None,
        source_type: str | None = None,
        source_id: uuid.UUID | None = None,
        is_system_generated: bool = False,
    ) -> JournalEntry:
        """Validate and post a journal entry. Returns the posted entry.

        All validation gates must pass, or PostingError is raised and nothing
        is written. The caller owns the transaction — this method only flushes.
        """
        # Gate 1: find open period.
        period = await self._period_repo.get_open_period(request.posting_date)
        if period is None:
            raise PostingError(
                f"No open fiscal period for date {request.posting_date}.",
                code="period_not_open",
            )

        # Gate 2: validate each line's account exists and is postable.
        for line in request.lines:
            account = await self._account_repo.get(line.account_id)
            if account is None:
                raise PostingError(
                    f"Account {line.account_id} not found.",
                    code="account_not_found",
                )
            if not account.is_active:
                raise PostingError(
                    f"Account {account.code} is inactive.",
                    code="account_inactive",
                )
            if not account.is_postable:
                raise PostingError(
                    f"Account {account.code} is not postable (header account only).",
                    code="account_not_postable",
                )
            # Gate 3: control accounts reject manual posting.
            if account.is_control and not is_system_generated:
                raise PostingError(
                    f"Account {account.code} ({account.name}) is a control account "
                    "and can only be posted by the system via sub-ledgers.",
                    code="control_account_violation",
                )

        # Gate 4: all-zero check — every line must have something.
        for line in request.lines:
            if line.dr == 0 and line.cr == 0:
                raise PostingError(
                    "Every journal line must have a non-zero debit or credit.",
                    code="zero_amount_line",
                )
            if line.dr != 0 and line.cr != 0:
                raise PostingError(
                    "A journal line cannot have both debit and credit populated.",
                    code="both_dr_and_cr",
                )

        # Gate 5: balance — base-currency debits must equal credits.
        total_dr = money_sum(line.dr_base for line in request.lines)
        total_cr = money_sum(line.cr_base for line in request.lines)
        if total_dr != total_cr:
            raise PostingError(
                f"Journal is unbalanced: total debit {total_dr} ≠ "
                f"total credit {total_cr} (base currency).",
                code="unbalanced",
            )

        # All gates passed — write the entry.
        now = datetime.now(tz=timezone.utc)
        entry = await self._entry_repo.create(
            entry_no=await _next_entry_no(
                self._session, request.voucher_type, request.posting_date
            ),
            posting_date=request.posting_date,
            period_id=period.id,
            voucher_type=request.voucher_type,
            description=request.description,
            source_type=source_type,
            source_id=source_id,
            status=JournalStatus.POSTED.value,
            posted_at=now,
            cheque_no=request.cheque_no,
            cheque_date=request.cheque_date,
            is_opening=request.is_opening,
            is_system_generated=is_system_generated,
            user_remark=request.user_remark,
        )

        for line_req in request.lines:
            entry.lines.append(
                JournalLine(
                    entry_id=entry.id,
                    account_id=line_req.account_id,
                    description=line_req.description,
                    dr=line_req.dr,
                    cr=line_req.cr,
                    dr_base=line_req.dr_base,
                    cr_base=line_req.cr_base,
                    currency_code=line_req.currency_code,
                    fx_rate=line_req.fx_rate,
                    party_type=line_req.party_type,
                    party_id=line_req.party_id,
                )
            )

        # Append audit row — domain modules call AuditRepository.append directly
        # so the audit insert shares the caller's transaction.
        from app.modules.audit.repository import AuditRepository

        audit_repo = AuditRepository(self._session)
        await audit_repo.append(
            actor_type="agent" if actor_id else "system",
            actor_id=actor_id,
            action="ledger.entry_posted",
            entity_type="journal_entry",
            entity_id=entry.id,
            after_state={
                "entry_no": entry.entry_no,
                "posting_date": str(entry.posting_date),
                "description": entry.description,
                "total_dr": str(total_dr),
                "total_cr": str(total_cr),
            },
        )

        await self._session.flush()

        emit_event(
            "ledger.entry_posted",
            entry_id=str(entry.id),
            entry_no=entry.entry_no,
            source_type=source_type,
            source_id=str(source_id) if source_id else None,
        )
        return entry

    async def reverse(
        self,
        entry_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        reversal_date: date | None = None,
    ) -> JournalEntry:
        """Reverse a posted journal entry by creating a mirror entry."""
        entry = await self._entry_repo.get_with_lines(entry_id)
        if entry is None:
            raise PostingError(
                f"Journal entry {entry_id} not found.",
                code="entry_not_found",
            )
        if entry.status != JournalStatus.POSTED.value:
            raise PostingError(
                f"Only posted entries can be reversed. Current status: {entry.status}.",
                code="cannot_reverse_unposted",
            )
        if entry.reversed_by_id is not None:
            raise PostingError(
                f"Entry {entry.entry_no} has already been reversed.",
                code="already_reversed",
            )

        pd = reversal_date or entry.posting_date
        lines = [
            JournalLineRequest(
                account_id=line.account_id,
                description=f"Reversal of {entry.entry_no}: {line.description or ''}",
                dr=line.cr,
                cr=line.dr,
                dr_base=line.cr_base,
                cr_base=line.dr_base,
                currency_code=line.currency_code,
                fx_rate=line.fx_rate,
                party_type=line.party_type,
                party_id=line.party_id,
            )
            for line in entry.lines
        ]

        reversal_req = JournalEntryCreateRequest(
            posting_date=pd,
            description=f"Reversal of {entry.entry_no}",
            voucher_type=entry.voucher_type,
            lines=lines,
            is_opening=False,
        )

        reversal = await self.post(
            reversal_req,
            actor_id=actor_id,
            source_type="journal_entry",
            source_id=entry_id,
            is_system_generated=False,
        )

        # Mark original as reversed.
        entry.status = JournalStatus.REVERSED.value
        entry.reversed_by_id = reversal.id
        await self._session.flush()

        emit_event(
            "ledger.entry_reversed",
            original_entry_id=str(entry_id),
            reversal_entry_id=str(reversal.id),
        )
        return reversal


# --------------------------------------------------------------- helpers

_NUMBER_SEQUENCE_LOCK_SQL = (
    "SELECT next_value FROM number_sequences "
    "WHERE doc_type = :doc_type AND fiscal_year = :fy "
    "FOR UPDATE"
)


async def _next_entry_no(session, voucher_type: str, posting_date: date) -> str:
    """Allocate the next gapless entry number for *voucher_type*.

    Uses SELECT ... FOR UPDATE row lock on number_sequences to prevent gaps
    under concurrent writers. The sequence is scoped to the fiscal year of
    *posting_date* (not today), so backdated entries are numbered in the year
    they belong to.
    """
    fiscal_year = posting_date.year
    prefix = {
        "journal_entry": "JV",
        "bank_entry": "BP",
        "cash_entry": "CP",
        "contra_entry": "CNT",
        "credit_note": "CRN",
        "debit_note": "DBN",
        "write_off": "WO",
        "opening_entry": "OP",
        "exchange_gain_loss": "FX",
    }.get(voucher_type, "JV")

    result = await session.execute(
        text(_NUMBER_SEQUENCE_LOCK_SQL),
        {"doc_type": voucher_type, "fy": fiscal_year},
    )
    row = result.one_or_none()

    if row is None:
        # First entry of the year — create the sequence row.
        next_val = 1
        await session.execute(
            text(
                "INSERT INTO number_sequences (doc_type, fiscal_year, next_value) "
                "VALUES (:doc_type, :fy, :next_val)"
            ),
            {"doc_type": voucher_type, "fy": fiscal_year, "next_val": 2},
        )
    else:
        next_val = row[0]
        await session.execute(
            text(
                "UPDATE number_sequences SET next_value = :next_val "
                "WHERE doc_type = :doc_type AND fiscal_year = :fy"
            ),
            {"next_val": next_val + 1, "doc_type": voucher_type, "fy": fiscal_year},
        )

    return f"{prefix}-{fiscal_year}-{next_val:05d}"
