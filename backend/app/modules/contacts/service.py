"""Contact service — business rules around contacts.

Mirrors the ConversationService pattern: takes a session, builds its own
repositories, flushes audit rows in the same transaction. Routers commit.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.modules.audit.repository import AuditRepository
from app.modules.contacts.import_csv import (
    MAX_IMPORT_ROWS,
    ParsedContactRow,
    ParseError,
    parse_csv,
)
from app.modules.contacts.models import Contact
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import (
    BulkActionFailure,
    BulkActionResponse,
    BulkPatch,
    ContactCreateRequest,
    ContactImportReceipt,
    ContactImportRowError,
    ContactListFilters,
    ContactUpdateRequest,
)

_IMPORT_ERROR_CAP = 100


_SNAPSHOT_FIELDS = (
    "phone",
    "name",
    "company",
    "status",
    "notes",
    "information",
    "assigned_agent_id",
    "ai_assigned",
    "estimated_ltv",
)


def _snapshot(contact: Contact) -> dict[str, Any]:
    """Capture a JSONB-safe snapshot of fields that participate in audit diffs."""
    snap: dict[str, Any] = {}
    for f in _SNAPSHOT_FIELDS:
        value = getattr(contact, f, None)
        if value is None:
            snap[f] = None
        elif isinstance(value, uuid.UUID):
            snap[f] = str(value)
        else:
            snap[f] = str(value) if not isinstance(value, (str, int, float, bool)) else value
    return snap


def _normalize_assignment(kwargs: dict[str, Any]) -> None:
    """Keep ai_assigned and assigned_agent_id mutually exclusive.

    When ai_assigned is set to True, clear any human agent assignment.
    When a human agent is assigned, clear the AI flag.
    """
    if kwargs.get("ai_assigned") is True:
        kwargs["assigned_agent_id"] = None
    elif kwargs.get("assigned_agent_id") is not None:
        kwargs["ai_assigned"] = False


class ContactService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ContactRepository(session)
        self._audit = AuditRepository(session)

    # ----------------------------------------------------------------- reads

    async def list_contacts(
        self,
        *,
        filters: ContactListFilters,
        page: int,
        page_size: int,
    ) -> tuple[list[Contact], int]:
        offset = max(0, (page - 1) * page_size)
        items, total = await self._repo.list_with_filters(
            q=filters.q,
            status=filters.status_list,
            assigned_agent_id=filters.assigned_agent_id,
            tag_ids=filters.tag_id_list,
            has_assigned_agent=filters.has_assigned_agent,
            ai_assigned=filters.ai_assigned,
            order_by=filters.order_by,
            limit=page_size,
            offset=offset,
        )
        return items, total

    async def get_contact(self, contact_id: uuid.UUID) -> Contact:
        return await self._repo.get_or_404(contact_id)

    # ---------------------------------------------------------------- writes

    async def create_contact(
        self,
        *,
        payload: ContactCreateRequest,
        actor_id: uuid.UUID,
    ) -> Contact:
        """
        Create-only (not upsert): if a contact with this phone exists,
        raise ConflictError so the caller surfaces a 409. The webhook
        path uses ContactRepository.upsert_by_phone for the upsert flow.
        """
        existing = await self._repo.get_by_phone(payload.phone)
        if existing is not None:
            raise ConflictError(
                f"Contact with phone {payload.phone!r} already exists.",
                details={"contact_id": str(existing.id)},
            )

        kwargs = payload.model_dump(exclude_none=True)
        _normalize_assignment(kwargs)
        contact = await self._repo.create(**kwargs)

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,
            action="contact.created",
            entity_type="contact",
            entity_id=contact.id,
            before_state=None,
            after_state=_snapshot(contact),
        )
        await self._session.flush()
        return contact

    async def update_contact(
        self,
        *,
        contact_id: uuid.UUID,
        payload: ContactUpdateRequest,
        actor_id: uuid.UUID,
    ) -> Contact:
        contact = await self._repo.get_or_404(contact_id)
        before = _snapshot(contact)

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            # No-op update: still return the row (consistent with BaseRepository.update)
            return contact

        _normalize_assignment(updates)
        updated = await self._repo.update(contact_id, **updates)
        # update returns None only if the row vanished between get_or_404 and the
        # UPDATE — a concurrent delete; surface as a NotFoundError-equivalent.
        if updated is None:
            raise ConflictError(
                f"Contact {contact_id} disappeared during update.",
                details={"contact_id": str(contact_id)},
            )

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,
            action="contact.updated",
            entity_type="contact",
            entity_id=updated.id,
            before_state=before,
            after_state=_snapshot(updated),
        )
        await self._session.flush()
        return updated

    # ----------------------------------------------------------- bulk writes

    async def bulk_update(
        self,
        *,
        ids: list[uuid.UUID],
        patch: BulkPatch,
        actor_id: uuid.UUID,
    ) -> BulkActionResponse:
        """Patch a batch of contacts in one transaction.

        Per-id failures (missing contact) are collected and returned; the
        transaction is NOT rolled back for individual misses. One audit row
        is emitted summarising the call.
        """
        updates = patch.model_dump(exclude_unset=True)
        _normalize_assignment(updates)

        failed: list[BulkActionFailure] = []
        updated_ids: list[str] = []

        for cid in ids:
            contact = await self._repo.get(cid)
            if contact is None:
                failed.append(BulkActionFailure(id=cid, error="not_found"))
                continue
            row = await self._repo.update(cid, **updates)
            if row is None:
                failed.append(BulkActionFailure(id=cid, error="vanished"))
                continue
            updated_ids.append(str(cid))

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,
            action="contact.bulk_updated",
            entity_type="contact",
            entity_id=None,
            before_state=None,
            after_state={
                "patch": {
                    k: (str(v) if isinstance(v, uuid.UUID) else v)
                    for k, v in updates.items()
                },
                "target_ids": updated_ids,
                "count": len(updated_ids),
                "failed_count": len(failed),
            },
        )
        await self._session.flush()
        return BulkActionResponse(count=len(updated_ids), failed=failed)

    async def bulk_delete(
        self,
        *,
        ids: list[uuid.UUID],
        actor_id: uuid.UUID,
    ) -> BulkActionResponse:
        """Delete a batch of contacts. One audit row per call."""
        failed: list[BulkActionFailure] = []
        deleted_ids: list[str] = []

        for cid in ids:
            ok = await self._repo.delete(cid)
            if not ok:
                failed.append(BulkActionFailure(id=cid, error="not_found"))
                continue
            deleted_ids.append(str(cid))

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,
            action="contact.bulk_deleted",
            entity_type="contact",
            entity_id=None,
            before_state=None,
            after_state={
                "target_ids": deleted_ids,
                "count": len(deleted_ids),
                "failed_count": len(failed),
            },
        )
        await self._session.flush()
        return BulkActionResponse(count=len(deleted_ids), failed=failed)

    # --------------------------------------------------------- bulk CSV import

    async def import_csv(
        self,
        *,
        raw_bytes: bytes,
        actor_id: uuid.UUID,
    ) -> ContactImportReceipt:
        """Parse a CSV byte payload and upsert each row.

        Uses ``upsert_by_phone`` so re-uploading the same file is idempotent
        and concurrent uploads (e.g. duplicate submission) won't deadlock —
        the SAVEPOINT race recovery in the repository covers the unique
        contention window.

        Returns a ContactImportReceipt with counts and per-row error detail
        capped at the first 100 failures (avoids unbounded response payload).
        Emits a single audit event for the whole import — per-row audit
        rows would explode the audit log on large imports.
        """
        created = 0
        updated = 0
        skipped = 0
        errors: list[ContactImportRowError] = []
        total_rows = 0

        for parsed in parse_csv(raw_bytes, max_rows=MAX_IMPORT_ROWS):
            total_rows += 1
            if isinstance(parsed, ParseError):
                # The "missing phone column" header error is fatal — surface
                # it as a single error row and short-circuit.
                if parsed.error == "csv_missing_phone_column":
                    return ContactImportReceipt(
                        total_rows=0,
                        created=0,
                        updated=0,
                        skipped=0,
                        errors=[
                            ContactImportRowError(
                                row=parsed.row_number,
                                phone=parsed.phone,
                                error=parsed.error,
                            )
                        ],
                    )
                skipped += 1
                if len(errors) < _IMPORT_ERROR_CAP:
                    errors.append(
                        ContactImportRowError(
                            row=parsed.row_number,
                            phone=parsed.phone,
                            error=parsed.error,
                        )
                    )
                continue

            assert isinstance(parsed, ParsedContactRow)
            try:
                existed = await self._repo.get_by_phone(parsed.phone)
                contact = await self._repo.upsert_by_phone(
                    phone=parsed.phone, name=parsed.name
                )
                # Apply optional fields if the upsert returned an existing row
                # without them. We always overwrite if the CSV carries a value
                # — admin-uploaded data is treated as authoritative.
                changes: dict[str, object] = {}
                if parsed.name and contact.name != parsed.name:
                    changes["name"] = parsed.name
                if parsed.company and contact.company != parsed.company:
                    changes["company"] = parsed.company
                if changes:
                    await self._repo.update(contact.id, **changes)

                if existed is None:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:
                skipped += 1
                if len(errors) < _IMPORT_ERROR_CAP:
                    errors.append(
                        ContactImportRowError(
                            row=parsed.row_number,
                            phone=parsed.phone,
                            error=f"persist_error:{type(exc).__name__}",
                        )
                    )

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,
            action="contact.imported_csv",
            entity_type="contact",
            entity_id=None,
            before_state=None,
            after_state={
                "total_rows": total_rows,
                "created": created,
                "updated": updated,
                "skipped": skipped,
            },
        )
        await self._session.flush()

        return ContactImportReceipt(
            total_rows=total_rows,
            created=created,
            updated=updated,
            skipped=skipped,
            errors=errors,
        )
