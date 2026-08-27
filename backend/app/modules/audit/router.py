"""Audit log endpoints — admin-only viewer (DSD §9 / §7.1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_role_db
from app.modules.audit.schemas import AuditLogResponse
from app.modules.audit.service import AuditService
from app.schemas.common import Page

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=Page[AuditLogResponse])
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> Page[AuditLogResponse]:
    return await AuditService(session).list_logs(
        page=page,
        page_size=page_size,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
    )
