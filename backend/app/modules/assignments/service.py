"""Assignment service (DSD §4.8).

Two responsibilities:

1. Companion lock management endpoints — explicit acquire/renew/release of
   the conversation lock. The state-machine-coupled `assign` operation
   (which transitions to HUMAN_ASSIGNED while acquiring the lock) lives in
   `ConversationService.assign()`. These endpoints are for agents holding a
   thread open in the inbox without changing its state.

2. Round-robin auto-assignment — picks an active agent and delegates to
   `ConversationService.assign` so the resulting transition + audit + event
   emission go through the canonical path. Called internally by the AI
   orchestrator on escalation; not exposed as a public endpoint.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ConversationLockError
from app.modules.assignments.repository import AssignmentRepository
from app.modules.audit.repository import AuditRepository
from app.modules.auth.models import User
from app.modules.conversations.constants import LOCK_TIMEOUT_SECONDS
from app.modules.conversations.models import Conversation
from app.modules.conversations.repository import ConversationRepository
from app.modules.conversations.service import ConversationService


class AssignmentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AssignmentRepository(session)
        self._conv_repo = ConversationRepository(session)
        self._audit = AuditRepository(session)

    # ------------------------------------------------------------------ locks

    async def acquire_lock(
        self,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> Conversation:
        """Acquire (or renew) the conversation lock for the given agent.

        Raises ConversationLockError if another agent holds an unexpired lock.
        """
        # Ensure the conversation exists; surfaces a clean 404 instead of a
        # silent no-op from the conditional UPDATE.
        await self._conv_repo.get_or_404(conversation_id)

        ok = await self._conv_repo.acquire_lock(
            conversation_id, agent_id, LOCK_TIMEOUT_SECONDS
        )
        if not ok:
            raise ConversationLockError(
                "Conversation is locked by another agent.",
                details={"conversation_id": str(conversation_id)},
            )

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id or agent_id,
            action="conversation.locked",
            entity_type="conversation",
            entity_id=conversation_id,
            before_state=None,
            after_state={"locked_by": str(agent_id)},
        )
        await self._session.flush()
        return await self._conv_repo.get_or_404(conversation_id)

    async def renew_lock(
        self,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> Conversation:
        """Renew the lock TTL. Only succeeds if `agent_id` already holds it."""
        conv = await self._conv_repo.get_or_404(conversation_id)
        if conv.locked_by != agent_id:
            raise ConversationLockError(
                "Cannot renew a lock you do not hold.",
                details={"conversation_id": str(conversation_id)},
            )
        ok = await self._conv_repo.acquire_lock(
            conversation_id, agent_id, LOCK_TIMEOUT_SECONDS
        )
        if not ok:
            # Should be unreachable given the check above, but defensive.
            raise ConversationLockError(
                "Lock renewal failed.",
                details={"conversation_id": str(conversation_id)},
            )
        return await self._conv_repo.get_or_404(conversation_id)

    async def release_lock(
        self,
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        admin_override: bool = False,
    ) -> None:
        """Release the lock held by `agent_id`.

        With `admin_override=True`, releases regardless of holder — the
        router enforces that only admins may pass this flag.
        """
        conv = await self._conv_repo.get_or_404(conversation_id)
        if conv.locked_by is None:
            return  # idempotent
        if not admin_override and conv.locked_by != agent_id:
            raise ConversationLockError(
                "Cannot release a lock you do not hold.",
                details={"conversation_id": str(conversation_id)},
            )

        # The repository's release_lock requires (conversation_id, agent_id).
        # For admin override, pass the actual holder id.
        holder = conv.locked_by
        ok = await self._conv_repo.release_lock(conversation_id, holder)
        if not ok:
            # Lost a race with another release; treat as already-released.
            return

        await self._audit.append(
            actor_type="admin" if admin_override else "agent",
            actor_id=actor_id or agent_id,
            action="conversation.unlocked",
            entity_type="conversation",
            entity_id=conversation_id,
            before_state={"locked_by": str(holder)},
            after_state={"locked_by": None},
        )
        await self._session.flush()

    # ----------------------------------------------------- round-robin assign

    async def auto_assign(
        self,
        *,
        conversation_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> User:
        """Pick the next agent via round-robin and delegate to ConversationService.

        Raises ConflictError if no active agent is available.
        """
        agent = await self._repo.next_round_robin_agent()
        if agent is None:
            raise ConflictError(
                "No active agents available for auto-assignment.",
            )

        conv_service = ConversationService(self._session)
        await conv_service.assign(
            conversation_id=conversation_id,
            agent_id=agent.id,
            actor_id=actor_id or agent.id,
        )
        return agent
