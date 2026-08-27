"""Assignment endpoints (companion to /conversations/{id}/assign).

These manage the conversation lock without changing state. The full
"assign + transition to HUMAN_ASSIGNED" flow lives at
POST /conversations/{id}/assign and goes through ConversationService.assign.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user_db, get_db_session
from app.core.exceptions import ForbiddenError
from app.modules.assignments.schemas import LockRequest, LockResponse
from app.modules.assignments.service import AssignmentService

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.post(
    "/{conversation_id}/lock",
    response_model=LockResponse,
)
async def lock_conversation(
    conversation_id: uuid.UUID,
    payload: LockRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> LockResponse:
    """Acquire (or renew) the lock for the given agent.

    Agents may only lock for themselves. Admins may lock on behalf of any
    user (e.g. when reassigning a stuck conversation).
    """
    if payload.agent_id != current_user.id and current_user.role != "admin":
        raise ForbiddenError(
            "Cannot acquire a lock for another agent.",
        )

    service = AssignmentService(session)
    conv = await service.acquire_lock(
        conversation_id=conversation_id,
        agent_id=payload.agent_id,
        actor_id=current_user.id,
    )
    await session.commit()
    return LockResponse(
        conversation_id=conv.id,
        locked_by=conv.locked_by,  # type: ignore[arg-type]
        expires_at=conv.lock_expires_at,  # type: ignore[arg-type]
    )


@router.post(
    "/{conversation_id}/unlock",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlock_conversation(
    conversation_id: uuid.UUID,
    payload: LockRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> None:
    """Release the lock.

    Agents may only release their own lock. Admins may release any lock
    via admin_override (used to recover stuck conversations).
    """
    is_admin = current_user.role == "admin"
    if payload.agent_id != current_user.id and not is_admin:
        raise ForbiddenError(
            "Cannot release a lock you do not hold.",
        )

    service = AssignmentService(session)
    await service.release_lock(
        conversation_id=conversation_id,
        agent_id=payload.agent_id,
        actor_id=current_user.id,
        admin_override=is_admin and payload.agent_id != current_user.id,
    )
    await session.commit()


@router.post(
    "/{conversation_id}/renew",
    response_model=LockResponse,
)
async def renew_lock(
    conversation_id: uuid.UUID,
    payload: LockRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> LockResponse:
    """Extend the lock TTL. Only the current holder can renew."""
    if payload.agent_id != current_user.id:
        raise ForbiddenError("Cannot renew a lock for another agent.")

    service = AssignmentService(session)
    conv = await service.renew_lock(
        conversation_id=conversation_id, agent_id=payload.agent_id
    )
    await session.commit()
    return LockResponse(
        conversation_id=conv.id,
        locked_by=conv.locked_by,  # type: ignore[arg-type]
        expires_at=conv.lock_expires_at,  # type: ignore[arg-type]
    )
