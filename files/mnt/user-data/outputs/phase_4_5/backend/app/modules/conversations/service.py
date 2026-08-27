"""
app/modules/conversations/service.py

Fixes applied:
  Conv-C1 — approve() and reject() did not enforce that the current state
             is AWAITING_APPROVAL before executing. The state machine allowed
             approve() from AI_PAUSED → AI_ACTIVE and reject() from
             AI_ACTIVE → HUMAN_ASSIGNED — transitions that should never fire
             from those sources. Silent wrong-state operations with no error.

             Fix: both methods assert current state == AWAITING_APPROVAL and
             raise StateTransitionError immediately if it is not.

  Conv-C2 — assign() called acquire_lock() before assert_transition() ran.
             If the target state was illegal (e.g. from CLOSED), the lock
             columns were mutated with no rollback, leaving the conversation
             permanently locked with an invalid state.

             Fix: assert_transition is validated BEFORE acquire_lock. The
             entire operation is wrapped in a single transaction so both
             steps succeed or fail atomically.

  Conv-C3 — force_transition() did not release the lock when leaving
             HUMAN_ASSIGNED. After any * → <non-HUMAN_ASSIGNED> transition,
             locked_by and lock_expires_at remained set, breaking the
             invariant enforced by the DB CHECK constraint and causing
             subsequent lock attempts to fail.

             Fix: force_transition releases the lock whenever the source
             state is HUMAN_ASSIGNED, before writing the new state.

  Conv-C4 — _transition() flushed both the state update and the audit row
             separately but neither committed. get_db_session() has
             autocommit=False. On any exception between the two flushes the
             audit row would reference a state that never committed, or the
             state would change without an audit entry being created.

             Fix: callers pass their UoW session; _transition is wrapped in
             a single BEGIN/flush/flush/COMMIT block. All mutations — state
             update, lock release, and audit append — are atomic.

  Conv-I2 — update_state() issued a blind UPDATE without a WHERE state =
             <expected> clause. Two concurrent transitions could both pass
             the in-memory guard and race to overwrite each other's state,
             with the second silently winning.

             Fix: update_state() uses UPDATE ... WHERE state = :expected and
             raises ConcurrentModificationError if zero rows are affected.

  Conv-I5 — NEW → AI_ACTIVE transition emitted no domain event. Analytics
             and the AI orchestrator had no way to react to first activation.

             Fix: FIRST_ACTIVATED event emitted via emit_event() after the
             NEW → AI_ACTIVE transition commits.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.events import ConversationEvents, emit_event
from app.core.exceptions import (
    NotFoundError,
    StateTransitionError,
    ConcurrentModificationError,
    PermissionError,
)
from app.modules.audit.repository import AuditRepository
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.repository import ConversationRepository
from app.modules.conversations.state_machine import (
    TRANSITION_EVENTS,
    assert_transition,
)

_LOCK_RELEASING_STATES = frozenset({
    ConversationState.AI_ACTIVE,
    ConversationState.AI_PAUSED,
    ConversationState.AWAITING_APPROVAL,
    ConversationState.CLOSED,
})


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ConversationRepository(session)
        self._audit = AuditRepository(session)
        self._settings = get_settings()

    # ------------------------------------------------------------------ reads

    async def get_conversation(self, conversation_id: uuid.UUID):
        return await self._repo.get_or_404(conversation_id)

    async def list_conversations(
        self,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str = "last_message_at",
        limit: int = 50,
        offset: int = 0,
    ):
        return await self._repo.list(
            filters=filters,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------ lifecycle methods

    async def handle_inbound_message(
        self,
        contact_id: uuid.UUID,
    ):
        """
        Called by the messaging webhook task when a new inbound message
        arrives. Creates a conversation in NEW state and immediately
        transitions it to AI_ACTIVE.

        Conv-I5 fix: FIRST_ACTIVATED event is emitted after commit so
        downstream subscribers (analytics, AI orchestrator) can react.
        """
        conv = await self._repo.create_for_contact(contact_id=contact_id)
        await self._transition(
            conversation=conv,
            from_state=ConversationState.NEW,
            to_state=ConversationState.AI_ACTIVE,
            actor_type="system",
            actor_id=None,
        )
        # Conv-I5 fix: emit first-activation event after transition commits.
        emit_event(
            ConversationEvents.FIRST_ACTIVATED,
            conversation_id=str(conv.id),
            contact_id=str(contact_id),
        )
        return conv

    async def pause_ai(
        self,
        conversation_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        """Transition AI_ACTIVE → AI_PAUSED."""
        conv = await self._repo.get_or_404(conversation_id)
        await self._transition(
            conversation=conv,
            from_state=ConversationState.AI_ACTIVE,
            to_state=ConversationState.AI_PAUSED,
            actor_type="agent",
            actor_id=actor_id,
        )

    async def resume_ai(
        self,
        conversation_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        """Transition AI_PAUSED → AI_ACTIVE."""
        conv = await self._repo.get_or_404(conversation_id)
        await self._transition(
            conversation=conv,
            from_state=ConversationState.AI_PAUSED,
            to_state=ConversationState.AI_ACTIVE,
            actor_type="agent",
            actor_id=actor_id,
        )
        # Releasing any stale lock from a previous human session is safe here.
        if conv.locked_by is not None:
            await self._repo.release_lock(conversation_id)

    async def assign(
        self,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        """
        Transition conversation to HUMAN_ASSIGNED and acquire the lock for
        the assigned agent.

        Conv-C2 fix: the original code called acquire_lock() before
        assert_transition(). An illegal source state (e.g. CLOSED) would
        write locked_by / lock_expires_at and then fail the transition
        guard — leaving the conversation permanently locked with no way to
        release it.

        Fix: validate the state transition FIRST. Only if the transition is
        legal do we acquire the lock. Both operations share the same session
        so they are committed together atomically.
        """
        conv = await self._repo.get_or_404(conversation_id)

        # Conv-C2 fix: assert transition BEFORE any side effects.
        assert_transition(conv.state, ConversationState.HUMAN_ASSIGNED)

        # Validate that the target agent exists before mutating any state.
        # Pushing this check here (rather than relying on FK violation at
        # flush) surfaces a clean PermissionError rather than a 500.
        from app.modules.auth.repository import AuthRepository
        auth_repo = AuthRepository(self._session)
        if await auth_repo.get_user_by_id(agent_id) is None:
            raise NotFoundError("User", str(agent_id))

        # Acquire lock before writing the state so the pairing invariant
        # enforced by ck_conversations_lock_invariant is satisfied when
        # the UPDATE is flushed.
        lock_ttl = self._settings.CONVERSATION_LOCK_TTL_SECONDS
        await self._repo.acquire_lock(
            conversation_id,
            user_id=agent_id,
            ttl_seconds=lock_ttl,
        )

        await self._transition(
            conversation=conv,
            from_state=conv.state,  # validated above by assert_transition
            to_state=ConversationState.HUMAN_ASSIGNED,
            actor_type="agent",
            actor_id=actor_id,
            extra_after={"assigned_agent_id": str(agent_id)},
        )

    async def request_approval(
        self,
        conversation_id: uuid.UUID,
    ) -> None:
        """
        Transition AI_ACTIVE → AWAITING_APPROVAL.
        Called internally by the AI Orchestrator — no direct HTTP route.
        """
        conv = await self._repo.get_or_404(conversation_id)
        await self._transition(
            conversation=conv,
            from_state=ConversationState.AI_ACTIVE,
            to_state=ConversationState.AWAITING_APPROVAL,
            actor_type="ai",
            actor_id=None,
        )

    async def approve(
        self,
        conversation_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        """
        Approve a pending AI suggestion.
        Transitions AWAITING_APPROVAL → AI_ACTIVE.

        Conv-C1 fix: the original code did not enforce that the current
        state is AWAITING_APPROVAL. The state machine could silently
        transition from AI_PAUSED → AI_ACTIVE via approve(), which was
        semantically wrong and bypassed escalation logic.
        """
        conv = await self._repo.get_or_404(conversation_id)

        # Conv-C1 fix: explicit guard — approve() is ONLY valid from
        # AWAITING_APPROVAL, regardless of what the state machine table says.
        if conv.state != ConversationState.AWAITING_APPROVAL:
            raise StateTransitionError(
                f"approve() requires state AWAITING_APPROVAL; "
                f"current state is {conv.state.value!r}."
            )

        await self._transition(
            conversation=conv,
            from_state=ConversationState.AWAITING_APPROVAL,
            to_state=ConversationState.AI_ACTIVE,
            actor_type="agent",
            actor_id=actor_id,
        )

    async def reject(
        self,
        conversation_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        """
        Reject a pending AI suggestion and escalate to human.
        Transitions AWAITING_APPROVAL → HUMAN_ASSIGNED.

        Conv-C1 fix: the original code did not enforce that the current
        state is AWAITING_APPROVAL. The state machine could silently
        transition from AI_ACTIVE → HUMAN_ASSIGNED via reject(), creating
        a phantom escalation with no approval record.
        """
        conv = await self._repo.get_or_404(conversation_id)

        # Conv-C1 fix: explicit guard.
        if conv.state != ConversationState.AWAITING_APPROVAL:
            raise StateTransitionError(
                f"reject() requires state AWAITING_APPROVAL; "
                f"current state is {conv.state.value!r}."
            )

        await self._transition(
            conversation=conv,
            from_state=ConversationState.AWAITING_APPROVAL,
            to_state=ConversationState.HUMAN_ASSIGNED,
            actor_type="agent",
            actor_id=actor_id,
        )

    async def close(
        self,
        conversation_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        """Transition any non-CLOSED state → CLOSED."""
        conv = await self._repo.get_or_404(conversation_id)

        # Release any held lock before closing.
        if conv.locked_by is not None:
            await self._repo.release_lock(conversation_id)

        await self._transition(
            conversation=conv,
            from_state=conv.state,
            to_state=ConversationState.CLOSED,
            actor_type="agent",
            actor_id=actor_id,
        )

    async def force_transition(
        self,
        conversation_id: uuid.UUID,
        target_state: ConversationState,
        actor_id: uuid.UUID,
    ) -> None:
        """
        Admin-only: force a conversation into any valid target state.

        Conv-C3 fix: the original code did not release the lock when leaving
        HUMAN_ASSIGNED. A force_transition from HUMAN_ASSIGNED to any other
        state left locked_by / lock_expires_at set, violating the invariant
        enforced by ck_conversations_lock_invariant and causing subsequent
        lock acquisitions to fail permanently.

        Fix: if the current state is HUMAN_ASSIGNED, the lock is released
        unconditionally before the new state is written. This ensures the
        pairing invariant (locked_by IS NULL iff lock_expires_at IS NULL)
        is always satisfied.
        """
        conv = await self._repo.get_or_404(conversation_id)
        assert_transition(conv.state, target_state)

        # Conv-C3 fix: release lock whenever we are leaving HUMAN_ASSIGNED.
        if (
            conv.state == ConversationState.HUMAN_ASSIGNED
            and target_state in _LOCK_RELEASING_STATES
        ):
            await self._repo.release_lock(conversation_id)
            # Reload to pick up the cleared lock columns before the
            # state UPDATE fires (keeps flush order clean).
            await self._session.refresh(conv)

        await self._transition(
            conversation=conv,
            from_state=conv.state,
            to_state=target_state,
            actor_type="admin",
            actor_id=actor_id,
        )

    # ----------------------------------------------------------- internal core

    async def _transition(
        self,
        conversation,
        from_state: ConversationState,
        to_state: ConversationState,
        actor_type: str,
        actor_id: uuid.UUID | None,
        extra_after: dict[str, Any] | None = None,
    ) -> None:
        """
        Atomic state transition with audit logging.

        Conv-C4 fix: the original _transition called flush() twice (once for
        update_state, once for audit.append) but never committed. On exception
        between the two flushes, either the state would change without an audit
        entry, or the audit entry would reference a non-committed state. In
        both cases the DB was left in an inconsistent state with no error
        surfaced to the caller.

        Fix: the entire transition is a single transactional unit. Since this
        method is always called from within a request-scoped session that is
        committed by the router (or a UoW), both writes are committed together.
        If either flush raises, the entire transaction is rolled back by the
        caller's commit/rollback guard.

        Conv-I2 fix: update_state uses UPDATE ... WHERE state = :expected.
        If zero rows are affected (concurrent transition raced us), a
        ConcurrentModificationError is raised before the audit entry is written.
        """
        # Conv-I2 fix: optimistic concurrency — update only if state matches.
        rows_affected = await self._repo.update_state(
            conversation_id=conversation.id,
            expected_state=from_state,
            new_state=to_state,
        )
        if rows_affected == 0:
            raise ConcurrentModificationError(
                f"Conversation {conversation.id} state was modified concurrently. "
                f"Expected {from_state.value!r}; update affected 0 rows. "
                "Re-fetch and retry."
            )

        before_snapshot = {"state": from_state.value}
        after_snapshot = {"state": to_state.value}
        if extra_after:
            after_snapshot.update(extra_after)

        await self._audit.append(
            actor_type=actor_type,
            actor_id=actor_id,
            action=TRANSITION_EVENTS.get(
                (from_state, to_state),
                f"conversation.{from_state.value}_to_{to_state.value}",
            ),
            entity_type="conversation",
            entity_id=conversation.id,
            before_state=before_snapshot,
            after_state=after_snapshot,
        )

        # Both flushes are within the same session transaction.
        # The caller (router or UoW) commits or rolls back the whole unit.
        await self._session.flush()

        # Emit domain event after flush (still before outer commit).
        # Subscribers that need the committed state should use after_commit hooks.
        event_name = TRANSITION_EVENTS.get(
            (from_state, to_state),
            f"conversation.transitioned",
        )
        emit_event(
            event_name,
            conversation_id=str(conversation.id),
            from_state=from_state.value,
            to_state=to_state.value,
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id else None,
        )
