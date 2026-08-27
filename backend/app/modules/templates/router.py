"""Template endpoints (DSD §6.2).

Auth: GET is agent-or-admin; submit/sync are admin-only (template
management is a privileged, WABA-wide operation). The router commits
the unit of work after the service flushes — same Msg-C4 ordering as
contacts/conversations.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_role_db
from app.modules.templates.schemas import (
    TemplateImportResult,
    TemplateResponse,
    TemplateSubmitRequest,
)
from app.modules.templates.service import TemplateService
from app.schemas.common import Page

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=Page[TemplateResponse])
async def list_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> Page[TemplateResponse]:
    service = TemplateService(session)
    items, total = await service.list_templates(
        page=page, page_size=page_size, status=status_filter
    )
    return Page[TemplateResponse](
        items=[TemplateResponse.model_validate(t) for t in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/submit",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_template(
    payload: TemplateSubmitRequest,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> TemplateResponse:
    service = TemplateService(session)
    template = await service.submit_template(
        name=payload.name,
        category=payload.category.value,
        language=payload.language,
        body=payload.body,
    )
    await session.commit()
    return TemplateResponse.model_validate(template)


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> TemplateResponse:
    service = TemplateService(session)
    template = await service.get_template(template_id)
    return TemplateResponse.model_validate(template)


@router.post("/{template_id}/sync", response_model=TemplateResponse)
async def sync_template_status(
    template_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> TemplateResponse:
    service = TemplateService(session)
    template = await service.sync_status_from_meta(template_id)
    await session.commit()
    return TemplateResponse.model_validate(template)


@router.post("/import-from-meta", response_model=TemplateImportResult)
async def import_templates_from_meta(
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> TemplateImportResult:
    """Fetch all templates registered on the WABA from Meta and upsert locally.

    Useful for seeding the local DB with templates that were created directly
    in Meta Business Manager or via another tool.
    """
    service = TemplateService(session)
    result = await service.import_from_meta()
    await session.commit()
    return TemplateImportResult(**result)
