"""AI orchestration endpoints — admin inspection surface (DSD §10)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_role_db
from app.modules.ai.schemas import AIEventResponse
from app.modules.ai.service import AIEventReadService
from app.schemas.common import Page

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get(
    "/events/{conversation_id}",
    response_model=Page[AIEventResponse],
)
async def list_ai_events(
    conversation_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> Page[AIEventResponse]:
    """List AI round-trips recorded for one conversation.

    Admin-only because the request body (message_history, incoming_message)
    may contain customer PII. Ordered newest-first; ``total`` is a real
    COUNT so the client can paginate to the end.
    """
    rows, total = await AIEventReadService(session).list_by_conversation(
        conversation_id, page=page, page_size=page_size
    )
    return Page[AIEventResponse](
        items=[AIEventResponse.model_validate(r) for r in rows],
        page=page,
        page_size=page_size,
        total=total,
    )
