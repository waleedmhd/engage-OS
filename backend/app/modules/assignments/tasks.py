"""Assignments Celery tasks.

`expire_stale_locks_task` is the background reaper for conversation locks.

Lock state lives on `conversations.locked_by` / `conversations.lock_expires_at`
(paired by CHECK `ck_conversations_lock_invariant`). On `acquire_lock`, the
TTL is computed as `now() + LOCK_TIMEOUT_SECONDS`. If an agent stops renewing
(crashed tab, network drop), the inline check on the next `acquire_lock` call
clears the stale lock — but with no incoming acquire attempt, the row stays
locked forever. This task closes that gap.

Design notes:

  * Sync session (Celery invariant #3): uses `sync_session_factory`. The
    audit row is written via direct `session.add(AuditLog(...))` because
    `AuditRepository.append` is async-only. This matches the existing
    pattern in `contacts/tasks.py:144`.

  * `SELECT ... FOR UPDATE SKIP LOCKED` prevents two sweeper workers from
    contending if Celery ever runs concurrent reapers. `LIMIT` caps work
    per tick — backlog drains over subsequent ticks.

  * Per-row UPDATE re-asserts `locked_by = <prev_holder>` so a concurrent
    `release_lock` racing with the sweep is a no-op (no double-release,
    no spurious audit row).

  * Msg-C4 commit ordering: this task IS the outermost transaction owner,
    so the explicit `session.commit()` at the end is correct (not a
    service-layer commit).

  * No `self.retry()`: the next 30s tick retries naturally if anything
    transient went wrong.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select, update

from app.celery_app import celery_app
from app.core.events import ConversationEvents, emit_event
from app.db.session import sync_session_factory
from app.modules.assignments.constants import LOCK_EXPIRY_SWEEP_BATCH_LIMIT
from app.modules.audit.constants import ActorType
from app.modules.audit.models import AuditLog
from app.modules.conversations.models import Conversation

logger = structlog.get_logger(__name__)


@celery_app.task(name="assignments.tasks.expire_stale_locks_task", acks_late=True)
def expire_stale_locks_task() -> dict:
    """Release locks whose `lock_expires_at` is in the past.

    Returns a dict `{"released": N, "scanned": M}` for telemetry / tests.
    Conversation state is NOT changed — released conversations remain in
    HUMAN_ASSIGNED for manual pickup (user decision, plan §Context).
    """
    released = 0
    scanned = 0

    with sync_session_factory() as session:
        # Select expired locks with FOR UPDATE SKIP LOCKED so concurrent
        # sweepers don't fight over the same rows. The `now()` here is the
        # database clock — keeps the comparison consistent with the
        # `acquire_lock` UPDATE that wrote the expiry in the first place.
        stmt = (
            select(Conversation.id, Conversation.locked_by)
            .where(Conversation.locked_by.is_not(None))
            .where(Conversation.lock_expires_at < _utcnow_via_db())  # see below
            .order_by(Conversation.lock_expires_at)
            .limit(LOCK_EXPIRY_SWEEP_BATCH_LIMIT)
            .with_for_update(skip_locked=True)
        )

        rows = session.execute(stmt).all()
        scanned = len(rows)

        for conversation_id, prev_holder in rows:
            # Re-assert holder in the WHERE clause: if a concurrent
            # release_lock or new acquire_lock changed `locked_by`, this
            # UPDATE matches zero rows and we skip the audit write.
            upd = (
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .where(Conversation.locked_by == prev_holder)
                .values(locked_by=None, lock_expires_at=None)
                .returning(Conversation.id)
            )
            result = session.execute(upd)
            if result.scalar_one_or_none() is None:
                continue  # raced — leave for next tick or other actor

            # Audit row: actor_type=system, actor_id=None.
            # Direct AuditLog.add — AuditRepository.append is async-only.
            session.add(
                AuditLog(
                    actor_type=ActorType.SYSTEM.value,
                    actor_id=None,
                    action="conversation.lock_expired",
                    entity_type="conversation",
                    entity_id=conversation_id,
                    before_state={"locked_by": str(prev_holder)},
                    after_state={"locked_by": None},
                )
            )

            emit_event(
                ConversationEvents.LOCK_EXPIRED,
                conversation_id=str(conversation_id),
                previous_holder_id=str(prev_holder),
            )
            released += 1

        session.commit()

    logger.info(
        "expire_stale_locks_task_completed",
        scanned=scanned,
        released=released,
    )
    return {"scanned": scanned, "released": released}


def _utcnow_via_db():
    """Return SQLAlchemy `now()` expression bound to the DB clock.

    Using the database clock (rather than the worker's Python clock) keeps
    the comparison consistent with `ConversationRepository.acquire_lock`,
    which computes the TTL via Python `datetime.now(timezone.utc)` and
    stores it as a timestamptz. Both are UTC; comparing against `now() AT
    TIME ZONE 'UTC'` avoids subtle worker/server clock skew.
    """
    from sqlalchemy import func

    return func.now()
