"""AI Celery tasks (DSD §4.3, §4.4, §11).

Two tasks compose the AI flow:

  * ``request_ai_reply_task`` — calls the Claude cascade for an inbound
    message, persists the round-trip to ``ai_events``, and applies the
    decision engine. On retryable AI provider failures (timeout, 5xx,
    transport) it re-queues itself with an exponential backoff (10s / 30s /
    90s). When all retries are exhausted, falls back to assigning the
    conversation to a human (DSD §11).

  * ``send_ai_reply_task`` — delayed-dispatch wrapper for an auto-send draft.
    Verifies the conversation is still under AI control (race-guard against
    pause / human takeover) and hands off to the existing Meta dispatcher.

Concurrency guard (Issue 10):
  Two concurrent Celery workers for the same conversation_id would both pass
  the state-check and both call Claude — double-billing and duplicate
  decisions. A Redis NX key (TTL = total retry window) prevents this: the
  first worker acquires the key; the second worker sees it already set and
  exits cleanly. The key is released in a ``finally`` block so failures
  never leave a permanently locked conversation.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from celery import Task

from app.celery_app import celery_app
from app.core.exceptions import AIProviderError, AIProviderTimeoutError
from app.core.redis import get_sync_redis
from app.db.session import sync_session_factory
from app.modules.ai.service import AIOrchestrator
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.messaging.constants import MessageDeliveryStatus, MessageDirection
from app.modules.messaging.models import Message

logger = structlog.get_logger(__name__)

# Retry backoff for AI provider failures.
# DSD §4.1 outbound retry policy is for Meta sends; AI uses a tighter ladder.
_AI_RETRY_DELAYS = [10, 30, 90]
_AI_MAX_RETRIES = len(_AI_RETRY_DELAYS)

# Redis concurrency lock TTL: covers the full retry window plus a safety margin.
# total_retry_time = sum(_AI_RETRY_DELAYS) + AI_REQUEST_TIMEOUT_SECONDS * retries
# ≈ 10+30+90 + 15*3 = 175s → round up to 180s.
_AI_LOCK_TTL_SECONDS = 180
_AI_LOCK_KEY_PREFIX = "ai:lock:conv:"


def _acquire_ai_lock(conv_id: str) -> bool:
    """Acquire a Redis NX lock for the given conversation_id. Returns True if acquired."""
    redis = get_sync_redis()
    key = f"{_AI_LOCK_KEY_PREFIX}{conv_id}"
    return bool(redis.set(key, "1", nx=True, ex=_AI_LOCK_TTL_SECONDS))


def _release_ai_lock(conv_id: str) -> None:
    redis = get_sync_redis()
    redis.delete(f"{_AI_LOCK_KEY_PREFIX}{conv_id}")


@celery_app.task(
    name="ai.tasks.request_ai_reply_task",
    bind=True,
    max_retries=_AI_MAX_RETRIES,
    acks_late=True,
)
def request_ai_reply_task(
    self: Task,
    conversation_id: str,
    incoming_message: str,
) -> dict:
    """Run one Claude cascade round-trip for ``conversation_id`` and apply the result.

    Returns a JSON-friendly summary of the resulting Decision so that the
    Celery result backend (and tests) can observe what happened.
    """
    conv_uuid = uuid.UUID(conversation_id)

    # Concurrency guard: only one worker at a time may call Claude for a given
    # conversation. A second worker seeing the lock already held exits with a
    # noop — it was enqueued redundantly (e.g. two rapid inbound messages while
    # the first task was still running). The existing inbound message record is
    # already in DB; the first worker will process it correctly.
    if not _acquire_ai_lock(conversation_id):
        logger.info(
            "ai_request_skipped_lock_held",
            conversation_id=conversation_id,
        )
        return {"action": "noop", "reason": "ai_lock_held"}

    try:
        return _run_ai_request(self, conv_uuid, conversation_id, incoming_message)
    finally:
        # Always release — including on self.retry() which raises Retry exception.
        # If the task is being retried (self.retry raises), the lock is released
        # here and the next retry attempt will re-acquire it.
        _release_ai_lock(conversation_id)


def _run_ai_request(
    self: Task,
    conv_uuid: uuid.UUID,
    conversation_id: str,
    incoming_message: str,
) -> dict:
    """Inner implementation, separated to keep the lock-acquire/release clean."""
    decision = None

    with sync_session_factory() as session:
        orchestrator = AIOrchestrator(session=session)

        # Skip if AI is no longer in charge — handles the race where a human
        # took over between webhook ingestion and this task running.
        conv = session.get(Conversation, conv_uuid)
        if conv is None:
            logger.warning(
                "ai_request_conversation_missing",
                conversation_id=conversation_id,
            )
            return {"action": "noop", "reason": "conversation_missing"}
        if not conv.ai_enabled or conv.state in {
            ConversationState.HUMAN_ASSIGNED.value,
            ConversationState.AI_PAUSED.value,
            ConversationState.CLOSED.value,
        }:
            logger.info(
                "ai_request_skipped_non_ai_state",
                conversation_id=conversation_id,
                state=conv.state,
                ai_enabled=conv.ai_enabled,
            )
            return {"action": "noop", "reason": "ai_disabled_or_handed_off"}

        try:
            decision = orchestrator.process_inbound(
                conv_uuid, incoming_message=incoming_message
            )
        except (AIProviderTimeoutError, AIProviderError) as exc:
            attempt = self.request.retries  # 0-indexed
            retryable = getattr(exc, "retryable", False)
            if retryable and attempt < len(_AI_RETRY_DELAYS):
                delay = _AI_RETRY_DELAYS[attempt]
                logger.warning(
                    "ai_request_retry_scheduled",
                    conversation_id=conversation_id,
                    attempt=attempt + 1,
                    delay_seconds=delay,
                    error=exc.code,
                )
                raise self.retry(exc=exc, countdown=delay) from exc

            # Exhausted retries (or non-retryable) → DSD §11 fallback.
            logger.error(
                "ai_request_assigning_human",
                conversation_id=conversation_id,
                error=exc.code,
                retryable=retryable,
                attempt=attempt,
            )
            # Fresh session: the orchestrator's session committed the failure
            # ai_event row and raised. Open a new session for the fallback.
            with sync_session_factory() as fallback_session:
                AIOrchestrator(session=fallback_session).assign_human(
                    conv_uuid,
                    reason=f"ai_provider_failure:{exc.code}",
                )
            return {
                "action": "escalate",
                "reason": f"ai_provider_failure:{exc.code}",
            }

    # Auto-send: enqueue the delayed dispatch AFTER the session has closed and
    # committed (DSD §4.4 realistic delay engine).
    if decision is not None and decision.action == "auto_send" and decision.draft_message_id is not None:
        send_ai_reply_task.apply_async(
            args=[conversation_id, str(decision.draft_message_id)],
            countdown=decision.delay_seconds or 0,
        )

    if decision is None:
        return {"action": "noop", "reason": "unexpected_early_return"}

    return {
        "action": decision.action,
        "delay_seconds": decision.delay_seconds,
        "draft_message_id": (
            str(decision.draft_message_id) if decision.draft_message_id else None
        ),
        "tag_suggestion_ids": [str(t) for t in decision.tag_suggestion_ids],
        "reason": decision.reason,
    }


@celery_app.task(
    name="ai.tasks.send_ai_reply_task",
    bind=True,
    max_retries=2,
    acks_late=True,
)
def send_ai_reply_task(
    self: Task,
    conversation_id: str,
    draft_message_id: str,
) -> dict:
    """Delayed-dispatch for an AI-authored reply (DSD §4.4).

    Race guard: if a human has paused/taken over the conversation between the
    auto-send decision and this task firing, the draft is NOT sent. The draft
    row is left in QUEUED state so a human can still send/discard it via the
    inbox.
    """
    from app.modules.messaging.tasks import send_outbound_message_task

    conv_uuid = uuid.UUID(conversation_id)
    msg_uuid = uuid.UUID(draft_message_id)

    with sync_session_factory() as session:
        conv = session.get(Conversation, conv_uuid)
        message = session.get(Message, msg_uuid)

        if conv is None or message is None:
            logger.warning(
                "send_ai_reply_missing_row",
                conversation_id=conversation_id,
                draft_message_id=draft_message_id,
            )
            return {"sent": False, "reason": "row_missing"}

        if not conv.ai_enabled or conv.state in {
            ConversationState.HUMAN_ASSIGNED.value,
            ConversationState.AI_PAUSED.value,
            ConversationState.AWAITING_APPROVAL.value,
            ConversationState.CLOSED.value,
        }:
            logger.info(
                "send_ai_reply_aborted_state_changed",
                conversation_id=conversation_id,
                draft_message_id=draft_message_id,
                state=conv.state,
                ai_enabled=conv.ai_enabled,
            )
            return {"sent": False, "reason": "state_no_longer_ai_active"}

        if message.delivery_status != MessageDeliveryStatus.QUEUED.value:
            logger.info(
                "send_ai_reply_aborted_message_status",
                draft_message_id=draft_message_id,
                status=message.delivery_status,
            )
            return {"sent": False, "reason": "message_not_queued"}

    # Session closed cleanly above. Enqueue OUTSIDE the with-block.
    send_outbound_message_task.delay(draft_message_id)
    return {"sent": True, "draft_message_id": draft_message_id}


# ------------------------------------------------------------------ AI resume


@celery_app.task(
    name="ai.tasks.update_memory_on_ai_resume",
    bind=True,
    max_retries=1,
)
def update_memory_on_ai_resume(
    self: Task,
    conversation_id: str,
) -> dict:
    """Update contact memory when a conversation resumes AI handling.

    Called after HUMAN_ASSIGNED → AI_ACTIVE transitions. Loads the full
    chat history (including human-handled messages), updates or creates
    the contact's memory file, and dispatches AI processing for any
    unreplied customer messages.
    """
    import sqlalchemy as sa

    conv_uuid = uuid.UUID(conversation_id)

    with sync_session_factory() as session:
        conv = session.get(Conversation, conv_uuid)
        if conv is None:
            return {"action": "noop", "reason": "conversation_missing"}

        logger.info(
            "ai_resume_memory_update_start",
            conversation_id=conversation_id,
            contact_id=str(conv.contact_id),
        )

        # Load full chat history for this conversation.
        limit = 200  # generous window to capture the human-handled exchange
        rows = session.execute(
            sa.select(
                Message.id,
                Message.direction,
                Message.sender_type,
                Message.content,
                Message.created_at,
            )
            .where(Message.conversation_id == conv_uuid)
            .order_by(Message.created_at.desc())
            .limit(limit)
        ).all()

        if not rows:
            return {"action": "noop", "reason": "no_history"}

        history: list[dict[str, Any]] = []
        for row in reversed(rows):
            role = "user" if row.direction == MessageDirection.INBOUND else "assistant"
            history.append(
                {
                    "id": str(row.id),
                    "role": role,
                    "sender_type": str(row.sender_type),
                    "content": row.content,
                    "created_at": row.created_at.isoformat()
                    if row.created_at
                    else None,
                }
            )

        from app.modules.contacts.memory_service import (
            update_memory_from_history_sync,
        )

        try:
            update_memory_from_history_sync(
                session,
                conv.contact_id,
                messages=history,
            )
            session.commit()
            logger.info(
                "ai_resume_memory_updated",
                conversation_id=conversation_id,
                contact_id=str(conv.contact_id),
                message_count=len(history),
            )
        except Exception:
            logger.warning(
                "ai_resume_memory_update_failed",
                conversation_id=conversation_id,
                exc_info=True,
            )
            return {"action": "noop", "reason": "memory_update_failed"}

    # Check for unreplied customer messages and trigger AI processing.
    unreplied = _find_unreplied_inbound(conversation_id)
    if unreplied:
        request_ai_reply_task.delay(conversation_id, unreplied)
        logger.info(
            "ai_resume_triggered_for_unreplied",
            conversation_id=conversation_id,
        )
        return {"action": "ai_triggered", "incoming_message": unreplied[:200]}

    return {"action": "memory_updated", "reason": "no_unreplied_messages"}


def _find_unreplied_inbound(conversation_id: str) -> str | None:
    """Return the content of the most recent unreplied customer message.

    A message is considered unreplied if there is no outbound message
    (from AI or human agent) timestamped after it.
    """
    import sqlalchemy as sa

    conv_uuid = uuid.UUID(conversation_id)

    with sync_session_factory() as session:
        row = session.execute(
            sa.select(Message.content, Message.created_at)
            .where(
                Message.conversation_id == conv_uuid,
                Message.direction == MessageDirection.INBOUND.value,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        ).one_or_none()

        if row is None:
            return None

        content, created_at = row

        has_reply = session.execute(
            sa.select(sa.func.count(Message.id))
            .where(
                Message.conversation_id == conv_uuid,
                Message.direction == MessageDirection.OUTBOUND.value,
                Message.created_at > created_at,
            )
        ).scalar_one()

        if has_reply == 0:
            return content

        return None
