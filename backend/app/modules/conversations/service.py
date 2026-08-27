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

  Conv-S2 — pause_ai() and close() never verified that the caller holds the
             conversation lock. Any authenticated user could pause or close
             a conversation owned by a different agent by simply calling the
             endpoint with the conversation ID. resume_ai() released the
             existing holder's lock without verifying the caller's identity.

             Fix: _assert_actor_holds_lock() checks that, when a non-expired
             lock is held, the caller's actor_id matches locked_by. The check
             is applied in pause_ai() and close(). resume_ai() is intentionally
             exempt — it clears a *stale* lock from a previous HUMAN_ASSIGNED
             session and any authenticated agent may do so.

  P0.3   — assign(), approve(), reject() gated by ROLE only: any agent
             could act on any conversation. assign() now refuses to steal a
             conversation actively locked by another agent (admin bypasses).
             approve()/reject() — AWAITING_APPROVAL has no lock, so ownership
             is gated on the contact's assigned_agent_id instead (see
             _assert_can_act_on_awaiting). admin bypasses everywhere.
             Conv-M5: locked_by is masked from non-admin/non-owner callers
             in the router responses.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.events import ConversationEvents, emit_event
from app.core.exceptions import (
    ConcurrentModificationError,
    ConflictError,
    NotFoundError,
    PermissionError,
    StateTransitionError,
    ValidationError,
)
from app.modules.audit.repository import AuditRepository
from app.modules.categorization.repository import ContactTagRepository, TagRepository
from app.modules.conversations.constants import LOCK_TIMEOUT_SECONDS, ConversationState
from app.modules.conversations.repository import ConversationRepository
from app.modules.conversations.state_machine import (
    TRANSITION_EVENTS,
    assert_transition,
    coerce,
)
from app.modules.contacts.schemas import BulkActionFailure, BulkActionResponse
from app.modules.messaging.constants import MessageDeliveryStatus
from app.modules.messaging.repository import MessageRepository

logger = structlog.get_logger(__name__)

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
        self._msg_repo = MessageRepository(session)
        self._audit = AuditRepository(session)
        self._settings = get_settings()

    # ------------------------------------------------------- private helpers

    def _assert_actor_holds_lock(
        self, conv, actor_id: uuid.UUID, actor_role: str | None = None
    ) -> None:
        """
        Conv-S2 fix: raise PermissionError if the conversation has an
        active (non-expired) lock held by a *different* actor.

        Called before mutating operations on potentially-locked conversations
        (pause_ai, close, assign). admin bypasses (matches force_transition
        being admin-only). Not applied to:
          - resume_ai   — clears a stale lock; any agent may act
          - force_transition — admin-only; bypasses lock ownership
        """
        if actor_role == "admin":
            return
        now = datetime.now(UTC)
        lock_active = (
            conv.locked_by is not None
            and conv.lock_expires_at is not None
            and conv.lock_expires_at.astimezone(UTC) > now
        )
        if lock_active and conv.locked_by != actor_id:
            raise PermissionError(
                f"Conversation {conv.id} is locked by another agent. "
                "Only the current lock holder may perform this operation."
            )

    async def _assert_can_act_on_awaiting(
        self, conv, actor_id: uuid.UUID, actor_role: str | None
    ) -> None:
        """
        P0.3 tenancy rule for approve()/reject().

        AWAITING_APPROVAL carries no conversation lock, so lock-ownership
        cannot gate it. Instead the owning agent is the contact's
        `assigned_agent_id`. Rule:
          - admin: always allowed (matches force_transition).
          - the assigned agent: allowed.
          - any other agent: PermissionError.
          - contact has NO assigned agent: allowed for any agent — there is
            no owner whose thread is being violated (the threat model is
            "agent B acting on agent A's thread"; with no agent A there is
            nothing to protect, and the AI approval queue would otherwise be
            unworkable for unassigned threads).
        """
        if actor_role == "admin":
            return
        from app.modules.contacts.models import Contact

        contact = await self._session.get(Contact, conv.contact_id)
        owner = getattr(contact, "assigned_agent_id", None) if contact else None
        if owner is not None and owner != actor_id:
            raise PermissionError(
                f"Conversation {conv.id} belongs to another agent. "
                "Only the assigned agent or an admin may approve/reject it."
            )

    # ------------------------------------------------------------------ reads

    async def get_conversation(self, conversation_id: uuid.UUID):
        return await self._repo.get_or_404(conversation_id)

    async def mark_read(self, conversation_id: uuid.UUID) -> None:
        """Record that the agent has viewed this conversation up to now."""
        await self._repo.touch_last_read(
            conversation_id, datetime.now(UTC)
        )

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
        actor_role: str | None = None,
    ) -> None:
        """Transition AI_ACTIVE → AI_PAUSED."""
        conv = await self._repo.get_or_404(conversation_id)
        # Conv-S2 fix: if another agent holds an active lock, reject the
        # operation. (When the conv is in AI_ACTIVE there is no lock, so
        # this check is a no-op in that case.)
        self._assert_actor_holds_lock(conv, actor_id, actor_role)
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
        actor_role: str | None = None,
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
        assert_transition(ConversationState(conv.state), ConversationState.HUMAN_ASSIGNED)

        # P0.3: a non-admin agent must not steal a conversation that is
        # actively locked by a different agent. If the conversation is
        # unlocked (e.g. AI_ACTIVE) this is a no-op and any agent may claim
        # it. admin bypasses.
        self._assert_actor_holds_lock(conv, actor_id, actor_role)

        # Validate that the target agent exists before mutating any state.
        # Pushing this check here (rather than relying on FK violation at
        # flush) surfaces a clean PermissionError rather than a 500.
        from app.modules.auth.repository import AuthRepository
        auth_repo = AuthRepository(self._session)
        if await auth_repo.get_user_by_id(agent_id) is None:
            raise NotFoundError(f"User {agent_id} not found")

        # Acquire lock before writing the state so the pairing invariant
        # enforced by ck_conversations_lock_invariant is satisfied when
        # the UPDATE is flushed.
        lock_ttl = getattr(
            self._settings, "CONVERSATION_LOCK_TTL_SECONDS", LOCK_TIMEOUT_SECONDS
        )
        # Phase 5 fix: previous code passed user_id= as a kwarg, but the
        # repository signature is (conversation_id, agent_id, ttl_seconds).
        # The TypeError this produced was masked because no test exercised
        # the assign path end-to-end. Phase 5's auto_assign path goes
        # through this method, so the kwarg name is corrected here.
        await self._repo.acquire_lock(
            conversation_id,
            agent_id,
            lock_ttl,
        )

        await self._transition(
            conversation=conv,
            from_state=ConversationState(conv.state),  # cast: Mapped[str] -> enum
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
        actor_role: str | None = None,
    ) -> uuid.UUID | None:
        """
        Approve a pending AI suggestion.
        Transitions AWAITING_APPROVAL → AI_ACTIVE and promotes the latest
        DRAFT outbound message to QUEUED so it can be delivered.

        B-11 contract: approval means "yes, send this reply". The latest
        DRAFT outbound message for the conversation is promoted DRAFT →
        QUEUED inside this same transaction (the router commits — Msg-C4).
        The promoted message id is returned so the router can dispatch
        send_outbound_message_task AFTER the commit; the service never
        dispatches the task itself (a task firing before commit would race
        an uncommitted QUEUED row). Returns None when there is no pending
        DRAFT — approval still transitions state but nothing is sent.

        No realistic-delay countdown is applied (unlike the FAQ auto-send
        path): a human has already reviewed and consciously approved, so
        the reply is dispatched immediately.

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
                f"current state is {ConversationState(conv.state).value!r}."
            )

        # P0.3: only the contact's assigned agent (or admin) may approve.
        await self._assert_can_act_on_awaiting(conv, actor_id, actor_role)

        await self._transition(
            conversation=conv,
            from_state=ConversationState.AWAITING_APPROVAL,
            to_state=ConversationState.AI_ACTIVE,
            actor_type="agent",
            actor_id=actor_id,
        )

        # B-11: promote the reviewed DRAFT → QUEUED in this transaction.
        # The router commits and then dispatches the send task (Msg-C4).
        draft = await self._msg_repo.get_latest_draft_outbound(conversation_id)
        if draft is None:
            return None
        await self._msg_repo.update_delivery_status(
            draft.id,
            MessageDeliveryStatus.QUEUED,
            last_error=None,
        )
        await self._session.flush()
        return draft.id

    async def reject(
        self,
        conversation_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_role: str | None = None,
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
                f"current state is {ConversationState(conv.state).value!r}."
            )

        # P0.3: only the contact's assigned agent (or admin) may reject.
        await self._assert_can_act_on_awaiting(conv, actor_id, actor_role)

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
        actor_role: str | None = None,
    ) -> None:
        """Transition any non-CLOSED state → CLOSED."""
        conv = await self._repo.get_or_404(conversation_id)

        # Conv-S2 fix: only the lock holder (or an unlocked/expired-lock
        # conversation) may be closed by a regular agent. admin bypasses.
        self._assert_actor_holds_lock(conv, actor_id, actor_role)

        # Release any held lock before closing.
        if conv.locked_by is not None:
            await self._repo.release_lock(conversation_id)

        await self._transition(
            conversation=conv,
            from_state=ConversationState(conv.state),
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
        from_state = ConversationState(conv.state)
        assert_transition(from_state, target_state)

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
            from_state=ConversationState(conv.state),
            to_state=target_state,
            actor_type="admin",
            actor_id=actor_id,
        )

        # When releasing a conversation from human handling back to AI,
        # re-enable AI and update the client memory so the AI agent has
        # context that includes the human-handled exchange.
        if (
            from_state == ConversationState.HUMAN_ASSIGNED
            and target_state == ConversationState.AI_ACTIVE
        ):
            conv.ai_enabled = True
            await self._session.flush()
            try:
                from app.modules.ai.tasks import update_memory_on_ai_resume
                update_memory_on_ai_resume.apply_async(
                    args=(str(conv.id),), retry=False
                )
            except Exception:
                logger.warning(
                    "ai_resume_task_dispatch_failed",
                    conversation_id=str(conv.id),
                    exc_info=True,
                )

    # ----------------------------------------------------------- bulk write

    async def bulk_update(
        self,
        *,
        ids: list[uuid.UUID],
        patch,  # BulkConversationPatch
        actor_id: uuid.UUID,
        actor_role: str | None = None,
    ) -> BulkActionResponse:
        """Patch a batch of conversations in one transaction.

        Per-id failures (not_found, invalid transition, lock contention) are
        collected and returned; processing continues for remaining IDs. One
        summary audit row is emitted for the whole call.
        """
        update_state = patch.state is not None
        add_tags: list[uuid.UUID] = patch.add_tag_ids or []
        remove_tags: list[uuid.UUID] = patch.remove_tag_ids or []

        # Pre-validate that referenced tags exist (one batch query each).
        tag_repo = TagRepository(self._session)
        if add_tags:
            for tid in add_tags:
                if await tag_repo.get(tid) is None:
                    raise NotFoundError(f"Tag:{tid}")
        if remove_tags:
            for tid in remove_tags:
                if await tag_repo.get(tid) is None:
                    raise NotFoundError(f"Tag:{tid}")

        target_state = ConversationState(patch.state) if update_state else None
        contact_tag_repo = ContactTagRepository(self._session)

        failed: list[BulkActionFailure] = []
        updated_ids: list[str] = []

        for cid in ids:
            conv = await self._repo.get(cid)
            if conv is None:
                failed.append(BulkActionFailure(id=cid, error="not_found"))
                continue

            try:
                if target_state is not None:
                    current = ConversationState(conv.state)
                    assert_transition(current, target_state)
                    # Lock check: non-admin agents can only transition conversations
                    # they hold the lock on (or that are unlocked).
                    if actor_role != "admin":
                        self._assert_actor_holds_lock(conv, actor_id, actor_role)

                    rows = await self._repo.update_state(
                        conversation_id=cid,
                        expected_state=current,
                        new_state=target_state,
                    )
                    if rows == 0:
                        failed.append(
                            BulkActionFailure(id=cid, error="concurrent_modification")
                        )
                        continue

                    # Release lock when leaving HUMAN_ASSIGNED.
                    if (
                        current == ConversationState.HUMAN_ASSIGNED
                        and target_state in _LOCK_RELEASING_STATES
                    ):
                        await self._repo.release_lock(cid)

                for tid in add_tags:
                    await contact_tag_repo.attach(
                        contact_id=conv.contact_id,
                        tag_id=tid,
                        approver_id=actor_id,
                    )
                for tid in remove_tags:
                    await contact_tag_repo.detach(
                        contact_id=conv.contact_id, tag_id=tid
                    )

                updated_ids.append(str(cid))

            except (
                StateTransitionError,
                ValidationError,
                PermissionError,
                ConflictError,
            ) as exc:
                failed.append(
                    BulkActionFailure(id=cid, error=str(exc))
                )
                continue

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,
            action="conversation.bulk_updated",
            entity_type="conversation",
            entity_id=None,
            before_state=None,
            after_state={
                "patch": {
                    k: (str(v) if isinstance(v, uuid.UUID) else v)
                    for k, v in patch.model_dump(exclude_unset=True).items()
                },
                "target_ids": updated_ids,
                "count": len(updated_ids),
                "failed_count": len(failed),
            },
        )
        await self._session.flush()
        return BulkActionResponse(count=len(updated_ids), failed=failed)

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
        # B-13: callers may pass `conversation.state` (a plain str loaded
        # from the DB) as from_state. Coerce both ends to the enum so the
        # `.value` accesses and TRANSITION_EVENTS lookups below are safe
        # regardless of whether the caller passed a str or an enum.
        from_state = coerce(from_state)
        to_state = coerce(to_state)

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
            "conversation.transitioned",
        )
        emit_event(
            event_name,
            conversation_id=str(conversation.id),
            from_state=from_state.value,
            to_state=to_state.value,
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id else None,
        )
