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

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_current_user_db,
    get_db_session,
    require_role_db,
)
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.repository import ConversationRepository
from app.modules.conversations import state_machine
from app.modules.contacts.models import Contact
from app.modules.conversations.schemas import (
    AssignRequest,
    BulkConversationUpdateRequest,
    ConversationContactSummary,
    ConversationListItem,
    ConversationResponse,
    ConversationTransitionRequest,
    NeedsHumanCountResponse,
)
from app.modules.contacts.schemas import BulkActionResponse
from app.modules.conversations.service import ConversationService
from app.schemas.common import Page

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _mask_lock(dto, user):
    """Conv-M5: do not leak which agent holds the lock to callers who are
    neither admin nor the lock holder themselves. The fact a conversation
    is locked is fine to expose implicitly via state; the *holder identity*
    is not. Mutates and returns the DTO."""
    if getattr(user, "role", None) == "admin":
        return dto
    if dto.locked_by is not None and dto.locked_by == user.id:
        return dto
    dto.locked_by = None
    dto.lock_expires_at = None
    return dto


@router.get("", response_model=Page[ConversationListItem])
async def list_conversations(
    state: str | None = None,
    tag_id: uuid.UUID | None = None,
    assigned_agent_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),  # any authenticated user
) -> Page[ConversationListItem]:
    """Inbox-shaped listing: each row carries the contact summary and the
    last message preview. Filters are AND-combined; `q` searches contact
    name/phone/company.
    """
    repo = ConversationRepository(session)
    offset = (page - 1) * page_size
    items, total = await repo.list_inbox(
        state=state,
        tag_id=tag_id,
        assigned_agent_id=assigned_agent_id,
        contact_id=contact_id,
        q=q,
        limit=page_size,
        offset=offset,
    )
    return Page[ConversationListItem](
        items=[
            _mask_lock(ConversationListItem.model_validate(i), current_user)
            for i in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/needs-human-count", response_model=NeedsHumanCountResponse)
async def needs_human_count(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> NeedsHumanCountResponse:
    """Count of conversations needing human intervention after AI escalation.

    Returns counts for AWAITING_APPROVAL and HUMAN_ASSIGNED states — the two
    states where a human agent must take action.
    """
    repo = ConversationRepository(session)
    counts = await repo.count_needs_human()
    return NeedsHumanCountResponse(**counts)


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> ConversationResponse:
    # Conv-M1 fix: routed through service, not repository directly.
    service = ConversationService(session)
    conv = await service.get_conversation(conversation_id)
    await service.mark_read(conversation_id)
    await session.commit()
    # Build response manually (not model_validate) — the ORM Conversation has a
    # "contact" relationship that from_attributes would try to lazy-load.
    resp = ConversationResponse(
        id=conv.id,
        contact_id=conv.contact_id,
        state=conv.state,
        ai_enabled=conv.ai_enabled,
        locked_by=conv.locked_by,
        lock_expires_at=conv.lock_expires_at,
        last_message_at=conv.last_message_at,
        allowed_transitions=sorted(
            s.value
            for s in state_machine.allowed_transitions(
                state_machine.coerce(conv.state)
            )
        ),
    )
    contact = await session.get(Contact, conv.contact_id)
    if contact is not None:
        resp.contact = ConversationContactSummary.model_validate(contact)
    # Conv-M5: mask lock holder from non-admin/non-owner callers.
    return _mask_lock(resp, current_user)


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
        actor_role=current_user.role,
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
        actor_role=current_user.role,
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
        actor_role=current_user.role,
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
    queued_message_id = await service.approve(
        conversation_id=conversation_id,
        actor_id=current_user.id,
        actor_role=current_user.role,
    )
    await session.commit()

    # Msg-C4: dispatch the send task only AFTER the commit so the worker
    # observes the committed QUEUED row. B-11: approval auto-sends the
    # reviewed reply immediately (no realistic-delay countdown).
    if queued_message_id is not None:
        from app.modules.messaging.tasks import send_outbound_message_task

        send_outbound_message_task.delay(str(queued_message_id))


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
        actor_role=current_user.role,
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
    current_user=Depends(require_role_db("admin")),
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


@router.post(
    "/bulk-update",
    response_model=BulkActionResponse,
    status_code=status.HTTP_200_OK,
)
async def bulk_update_conversations(
    payload: BulkConversationUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> BulkActionResponse:
    """Patch up to 100 conversations in one call.

    Admins may set any valid state transition and add/remove any tags.
    Agents may set state only for conversations they hold the lock on
    (or that are unlocked) and may add/remove tags.
    """
    service = ConversationService(session)
    result = await service.bulk_update(
        ids=payload.ids,
        patch=payload.patch,
        actor_id=current_user.id,
        actor_role=current_user.role,
    )
    await session.commit()
    return result
