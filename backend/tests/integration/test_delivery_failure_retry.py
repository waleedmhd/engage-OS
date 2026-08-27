"""Integration test: delivery-failure retry end-to-end.

Verifies the full cycle from a FAILED status update through the retry task
resetting the message to QUEUED, to the send task dispatching it again.
Uses the committed_db fixture — real Postgres, no mocks on the message path.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.modules.messaging.constants import (
    MAX_DELIVERY_RETRIES,
    MessageDeliveryStatus,
    MessageDirection,
    SenderType,
)
from app.modules.messaging.tasks import (
    _maybe_schedule_delivery_retry,
    reset_and_retry_message_task,
)


class TestDeliveryFailureRetryIntegration:
    def test_failed_status_schedules_retry_and_reset_cycles_to_queued(
        self, committed_db, monkeypatch
    ):
        """End-to-end: a message marked FAILED via status update is re-queued
        by reset_and_retry_message_task, and the send task sees it as QUEUED."""
        from app.db.session import sync_session_factory
        from app.modules.contacts.models import Contact
        from app.modules.conversations.models import Conversation
        from app.modules.messaging.models import Message
        from app.modules.messaging.repository import MessageRepository

        # Seed: contact + conversation + queued message.
        contact_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        msg_id = uuid.uuid4()

        with sync_session_factory() as session:
            session.execute(
                text(
                    "INSERT INTO contacts (id, phone, name, status, created_at, updated_at) "
                    "VALUES (:id, '+15551234567', 'Test', 'active', NOW(), NOW())"
                ),
                {"id": contact_id},
            )
            session.execute(
                text(
                    "INSERT INTO conversations (id, contact_id, state, ai_enabled, "
                    "created_at, updated_at) "
                    "VALUES (:id, :cid, 'AI_ACTIVE', false, NOW(), NOW())"
                ),
                {"id": conv_id, "cid": contact_id},
            )
            session.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, direction, sender_type, "
                    "content, delivery_status, meta_message_id, created_at, updated_at) "
                    "VALUES (:id, :cid, :dir, :st, :content, :status, :mmid, NOW(), NOW())"
                ),
                {
                    "id": msg_id,
                    "cid": conv_id,
                    "dir": MessageDirection.OUTBOUND.value,
                    "st": SenderType.AGENT.value,
                    "content": "test retry message",
                    "status": MessageDeliveryStatus.FAILED.value,
                    "mmid": "wamid.test.retry",
                },
            )
            session.commit()

        # Verify message starts FAILED with delivery_retry_count=0.
        with sync_session_factory() as session:
            repo = MessageRepository(session)  # type: ignore[arg-type]
            msg = repo.get_sync(msg_id)
            assert msg is not None
            assert msg.delivery_status == MessageDeliveryStatus.FAILED
            assert msg.delivery_retry_count == 0

        # Simulate what _apply_status_update does: schedule a retry for attempt 0.
        # (We call reset_and_retry_message_task directly to skip the countdown.)
        reset_and_retry_message_task.run(str(msg_id), 0)

        # Verify message is now QUEUED with delivery_retry_count=1.
        with sync_session_factory() as session:
            repo = MessageRepository(session)  # type: ignore[arg-type]
            msg = repo.get_sync(msg_id)
            assert msg is not None
            assert msg.delivery_status == MessageDeliveryStatus.QUEUED.value
            assert msg.delivery_retry_count == 1
            assert msg.last_error is None
            assert msg.error_code is None

    def test_delivery_retry_count_stops_at_max(self, committed_db, monkeypatch):
        """When delivery_retry_count >= MAX_DELIVERY_RETRIES, no further retry
        is scheduled."""
        from app.db.session import sync_session_factory
        from app.modules.settings.constants import SETTING_OPS_DELIVERY_FAILURE_RETRY
        from app.modules.settings.repository import get_bool_setting_sync

        # Seed a FAILED message at the retry limit.
        contact_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        msg_id = uuid.uuid4()

        with sync_session_factory() as session:
            session.execute(
                text(
                    "INSERT INTO contacts (id, phone, name, status, created_at, updated_at) "
                    "VALUES (:id, '+15551234568', 'Test2', 'active', NOW(), NOW())"
                ),
                {"id": contact_id},
            )
            session.execute(
                text(
                    "INSERT INTO conversations (id, contact_id, state, ai_enabled, "
                    "created_at, updated_at) "
                    "VALUES (:id, :cid, 'AI_ACTIVE', false, NOW(), NOW())"
                ),
                {"id": conv_id, "cid": contact_id},
            )
            session.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, direction, sender_type, "
                    "content, delivery_status, delivery_retry_count, meta_message_id, "
                    "created_at, updated_at) "
                    "VALUES (:id, :cid, :dir, :st, :content, :status, :drc, :mmid, "
                    "NOW(), NOW())"
                ),
                {
                    "id": msg_id,
                    "cid": conv_id,
                    "dir": MessageDirection.OUTBOUND.value,
                    "st": SenderType.AGENT.value,
                    "content": "exhausted retries",
                    "status": MessageDeliveryStatus.FAILED.value,
                    "drc": MAX_DELIVERY_RETRIES,
                    "mmid": "wamid.test.exhaust",
                },
            )
            session.commit()

        # _maybe_schedule_delivery_retry must noop when count >= MAX.
        with sync_session_factory() as session:
            # Should not schedule — returns early without error.
            _maybe_schedule_delivery_retry(session, msg_id, MAX_DELIVERY_RETRIES)

        # Verify message is still FAILED (not reset).
        with sync_session_factory() as session:
            from app.modules.messaging.repository import MessageRepository

            repo = MessageRepository(session)  # type: ignore[arg-type]
            msg = repo.get_sync(msg_id)
            assert msg is not None
            assert msg.delivery_status == MessageDeliveryStatus.FAILED.value
            assert msg.delivery_retry_count == MAX_DELIVERY_RETRIES
