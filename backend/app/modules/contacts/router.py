"""Contact endpoints (DSD §6.2).

Auth: agent or admin for all CRUD. Pagination via Page[T] from common schemas.
The router commits the unit of work after the service flushes its writes —
same pattern as conversations and auth (Auth-C1, Conv-C4 fixes).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_role_db
from app.modules.contacts.schemas import (
    BulkActionResponse,
    BulkDeleteRequest,
    BulkUpdateRequest,
    ContactCreateRequest,
    ContactImportReceipt,
    ContactListFilters,
    ContactResponse,
    ContactUpdateRequest,
    ContactUpsertRequest,
)
from app.modules.contacts.service import ContactService
from app.modules.contacts.repository import ContactRepository
from app.schemas.common import Page

# Hard cap on uploaded CSV size — 10MB. ~10k rows of typical CRM data fits
# well under this. Larger imports should land via the Celery task path.
_MAX_CSV_BYTES = 10 * 1024 * 1024

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=Page[ContactResponse])
async def list_contacts(
    filters: ContactListFilters = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> Page[ContactResponse]:
    service = ContactService(session)
    items, total = await service.list_contacts(
        filters=filters, page=page, page_size=page_size
    )
    return Page[ContactResponse](
        items=[ContactResponse.from_orm_with_tags(c) for c in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact(
    payload: ContactCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> ContactResponse:
    # Mirror the bulk-update rule: only admins may assign an agent on create.
    if current_user.role != "admin" and (
        payload.assigned_agent_id is not None or payload.ai_assigned
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="assign_admin_only",
        )
    service = ContactService(session)
    contact = await service.create_contact(payload=payload, actor_id=current_user.id)
    await session.commit()
    return ContactResponse.model_validate(contact)


@router.post(
    "/upsert",
    response_model=ContactResponse,
    status_code=status.HTTP_200_OK,
)
async def upsert_contact(
    payload: ContactUpsertRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> ContactResponse:
    """Create or update a contact by phone number.

    ``name`` is set only if the contact is new or currently has no name.
    ``information`` is APPENDED (never overwritten) so repeated calls
    accumulate context. The caller must have agent or admin role.
    """
    repo = ContactRepository(session)
    await repo.upsert_by_phone_append(
        phone=payload.phone,
        name=payload.name,
        information=payload.information,
    )
    await session.commit()
    # Reload after commit: server_default columns (created_at, updated_at)
    # are populated by the DB on COMMIT, not flush, and expire_on_commit
    # marks them stale. A fresh SELECT gives us a fully-attributed object
    # that Pydantic can read without triggering a lazy-load.
    contact = await repo.get_by_phone(payload.phone)
    return ContactResponse.model_validate(contact)


@router.post(
    "/bulk-update",
    response_model=BulkActionResponse,
    status_code=status.HTTP_200_OK,
)
async def bulk_update_contacts(
    payload: BulkUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> BulkActionResponse:
    """Patch up to 100 contacts in one call.

    Admins may set any patch field. Agents may set status only; including
    assigned_agent_id returns 400.
    """
    if (
        current_user.role != "admin"
        and (
            payload.patch.assigned_agent_id is not None
            or payload.patch.ai_assigned is not None
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="bulk_assign_admin_only",
        )

    service = ContactService(session)
    result = await service.bulk_update(
        ids=payload.ids, patch=payload.patch, actor_id=current_user.id
    )
    await session.commit()
    return result


@router.post(
    "/bulk-delete",
    response_model=BulkActionResponse,
    status_code=status.HTTP_200_OK,
)
async def bulk_delete_contacts(
    payload: BulkDeleteRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> BulkActionResponse:
    """Delete up to 100 contacts. Admin-only."""
    service = ContactService(session)
    result = await service.bulk_delete(
        ids=payload.ids, actor_id=current_user.id
    )
    await session.commit()
    return result


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> ContactResponse:
    service = ContactService(session)
    contact = await service.get_contact(contact_id)
    return ContactResponse.model_validate(contact)


@router.post(
    "/import",
    response_model=ContactImportReceipt,
    status_code=status.HTTP_200_OK,
)
async def import_contacts_csv(
    file: UploadFile = File(..., description="UTF-8 CSV with required `phone` column"),
    session: AsyncSession = Depends(get_db_session),
    # Bulk import is admin-only — it bypasses the per-contact create flow,
    # writes hundreds/thousands of rows in one transaction, and applies
    # admin-uploaded data as authoritative (overwrites name/company on hit).
    current_user=Depends(require_role_db("admin")),
) -> ContactImportReceipt:
    """Bulk-import contacts from a CSV file.

    Header row required. The `phone` column is mandatory; `name` and `company`
    are optional. See `app/modules/contacts/import_csv.py` for the full format
    spec.

    The endpoint commits the entire import atomically. If the file exceeds
    10MB or 10,000 rows, returns 413; the per-row error list in the receipt
    is capped at 100 entries so very dirty CSVs do not bloat the response.
    """
    raw = await file.read()
    if len(raw) > _MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"CSV exceeds {_MAX_CSV_BYTES // (1024 * 1024)}MB limit.",
        )

    service = ContactService(session)
    receipt = await service.import_csv(raw_bytes=raw, actor_id=current_user.id)
    await session.commit()
    return receipt


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: uuid.UUID,
    payload: ContactUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> ContactResponse:
    service = ContactService(session)
    contact = await service.update_contact(
        contact_id=contact_id, payload=payload, actor_id=current_user.id
    )
    await session.commit()
    return ContactResponse.model_validate(contact)
