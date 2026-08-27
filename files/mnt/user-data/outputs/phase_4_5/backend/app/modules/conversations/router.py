"""
app/modules/conversations/router.py

Fixes applied:
  Conv-S1 — force_transition endpoint had no role gate. Any authenticated
             user (including agents) could force any conversation into any
             state, including CLOSED. Combined with Conv-M4 (target_state
             accepting CLOSED), this was an uncontrolled close-any-conversation
             backdoor for all roles.

             Fix: force_transition is restricted to role=admin via
             require_role("admin").

  Conv-S3 — All override endpoints (pause_ai, resume_ai, assign, close,
             approve, reject) accepted any authenticated role with no
             distinction between agent and admin. Per DSD §6.1, admin has
             full access and agent has restricted operational access.

             Fix: role gates applied per endpoint:
               - pause_ai, resume_ai, assign, close: agent or admin
               - approve, reject: agent or admin (approval workflow)
               - force_transition: admin only

  Conv-M1 — get_conversation bypassed the service layer and called the
             repository directly from the router. This violates the
             router → service → repository constraint documented in
             docs/architecture.md. Fixed incidentally: all reads now
             route through ConversationService.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_current_user_db,
    get_db_session,
    require_role,
)
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.schemas import (
    AssignRequest,
    ConversationListResponse,
    ConversationResponse,
    ConversationTransitionRequest,
)
from app.modules.conversations.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    state: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(get_current_user_db),  # any authenticated user
) -> ConversationListResponse:
    service = ConversationService(session)
    filters = {"state": state} if state else None
    items = await service.list_conversations(
        filters=filters, limit=limit, offset=offset
    )
    return ConversationListResponse(
        items=[ConversationResponse.model_validate(c) for c in items],
        total=len(items),
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(get_current_user_db),
) -> ConversationResponse:
    # Conv-M1 fix: routed through service, not repository directly.
    service = ConversationService(session)
    conv = await service.get_conversation(conversation_id)
    return ConversationResponse.model_validate(conv)


@router.post("/{conversation_id}/assign", status_code=status.HTTP_204_NO_CONTENT)
async def assign_conversation(
    conversation_id: uuid.UUID,
    payload: AssignRequest,
    session: AsyncSession = Depends(get_db_session),
    # Conv-S3 fix: any authenticated user (agent or admin) may assign.
    current_user=Depends(get_current_user_db),
) -> None:
    service = ConversationService(session)
    await service.assign(
        conversation_id=conversation_id,
        agent_id=payload.agent_id,
        actor_id=current_user.id,
    )
    await session.commit()


@router.post("/{conversation_id}/pause-ai", status_code=status.HTTP_204_NO_CONTENT)
async def pause_ai(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    # Conv-S3 fix: agent or admin may pause AI.
    current_user=Depends(get_current_user_db),
) -> None:
    service = ConversationService(session)
    await service.pause_ai(
        conversation_id=conversation_id,
        actor_id=current_user.id,
    )
    await session.commit()


@router.post("/{conversation_id}/resume-ai", status_code=status.HTTP_204_NO_CONTENT)
async def resume_ai(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    # Conv-S3 fix: agent or admin may resume AI.
    current_user=Depends(get_current_user_db),
) -> None:
    service = ConversationService(session)
    await service.resume_ai(
        conversation_id=conversation_id,
        actor_id=current_user.id,
    )
    await session.commit()


@router.post("/{conversation_id}/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    # Conv-S3 fix: agent or admin may close.
    current_user=Depends(get_current_user_db),
) -> None:
    service = ConversationService(session)
    await service.close(
        conversation_id=conversation_id,
        actor_id=current_user.id,
    )
    await session.commit()


@router.post("/{conversation_id}/approve", status_code=status.HTTP_204_NO_CONTENT)
async def approve_suggestion(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    # Conv-S3 fix: agent or admin may approve.
    current_user=Depends(get_current_user_db),
) -> None:
    service = ConversationService(session)
    await service.approve(
        conversation_id=conversation_id,
        actor_id=current_user.id,
    )
    await session.commit()


@router.post("/{conversation_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_suggestion(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    # Conv-S3 fix: agent or admin may reject.
    current_user=Depends(get_current_user_db),
) -> None:
    service = ConversationService(session)
    await service.reject(
        conversation_id=conversation_id,
        actor_id=current_user.id,
    )
    await session.commit()


@router.post(
    "/{conversation_id}/transition",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def force_transition(
    conversation_id: uuid.UUID,
    payload: ConversationTransitionRequest,
    session: AsyncSession = Depends(get_db_session),
    # Conv-S1 fix: force_transition is restricted to admin role only.
    # Previously any authenticated user could force any conversation to
    # any state including CLOSED — a silent backdoor close endpoint.
    current_user=Depends(require_role("admin")),
) -> None:
    """
    Admin-only: force a conversation into a specified state.

    This endpoint bypasses normal transition guards and is intended for
    operational recovery only. All invocations are audit-logged.
    """
    service = ConversationService(session)
    await service.force_transition(
        conversation_id=conversation_id,
        target_state=ConversationState(payload.target_state),
        actor_id=current_user.id,
    )
    await session.commit()
