"""
app/modules/messaging/repository.py

Fixes applied:
  DB-C4  — update_delivery_status had an `if last_error is not None` guard
            before setting the last_error column. This prevented resetting
            last_error to NULL after a successful retry — the column retained
            its error string from the previous attempt even after the message
            was successfully sent, poisoning retry analytics and misleading
            support investigations.

            Fix: last_error is always written unconditionally. Passing
            last_error=None explicitly clears the column. The caller is
            responsible for providing the correct value.

  DB-I8  — increment_retry used a read-modify-write pattern:
                count = message.retry_count
                message.retry_count = count + 1
            Under concurrent retries (e.g. two Celery workers racing on
            the same message after a visibility timeout), both workers
            read the same count, both write count+1, and one increment
            is silently lost. Retry count analytics undercount real attempts.

            Fix: the increment is now a single atomic SQL statement:
                UPDATE messages
                SET retry_count = retry_count + 1
                WHERE id = :id
            This is the only correct approach for a counter that may be
            incremented concurrently.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import BaseRepository
from app.modules.messaging.constants import MessageDeliveryStatus, MessageDirection
from app.modules.messaging.models import Message


class MessageRepository(BaseRepository[Message]):
    model = Message

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_meta_id(self, meta_message_id: str) -> Message | None:
        """Look up a message by the Meta-assigned message ID."""
        result = await self.session.execute(
            sa.select(Message).where(Message.meta_message_id == meta_message_id)
        )
        return result.scalar_one_or_none()

    async def update_delivery_status(
        self,
        message_id: uuid.UUID,
        new_status: MessageDeliveryStatus,
        *,
        last_error: str | None,
        error_code: int | None = None,
        meta_message_id: str | None = None,
    ) -> None:
        """
        Update the delivery status and related fields on a message.

        DB-C4 fix: last_error is written unconditionally, not guarded by
        `if last_error is not None`. This allows callers to clear the
        last_error column by passing last_error=None after a successful
        retry, preventing stale error strings from persisting after the
        message has been successfully sent.

        Args:
            message_id:      UUID of the message to update.
            new_status:      The new delivery status value.
            last_error:      Error description on failure, or None to clear.
                             Explicitly pass None after a successful send
                             so previous failure details are not retained.
            error_code:      Meta Cloud API error code on failure, or None to clear.
            meta_message_id: Optional: set the Meta-assigned ID on first
                             successful send.
        """
        values: dict[str, Any] = {
            "delivery_status": new_status,
            # DB-C4 fix: always write last_error — no conditional guard.
            # None → SQL NULL (clears previous error after successful retry).
            "last_error": last_error,
            "error_code": error_code,
        }
        if meta_message_id is not None:
            values["meta_message_id"] = meta_message_id

        await self.session.execute(
            sa.update(Message)
            .where(Message.id == message_id)
            .values(**values)
        )

    async def increment_retry(self, message_id: uuid.UUID) -> None:
        """
        Atomically increment retry_count.

        DB-I8 fix: the previous implementation was a read-modify-write:
            message = await repo.get(id)
            message.retry_count = message.retry_count + 1
        Under concurrent Celery workers (e.g. two retries triggered by a
        visibility timeout), both workers could read the same count and
        both write count+1, losing one increment.

        This single SQL statement is atomic — it reads and writes the
        column in one round-trip without any opportunity for a concurrent
        worker to race between the read and the write.
        """
        await self.session.execute(
            sa.update(Message)
            .where(Message.id == message_id)
            # DB-I8 fix: server-side arithmetic — no Python read involved.
            .values(retry_count=Message.retry_count + 1)
        )

    async def get_pending_outbound(
        self,
        limit: int = 100,
    ) -> Sequence[Message]:
        """Return QUEUED outbound messages for dispatch."""
        result = await self.session.execute(
            sa.select(Message)
            .where(
                Message.delivery_status == MessageDeliveryStatus.QUEUED,
            )
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_latest_draft_outbound(
        self,
        conversation_id: uuid.UUID,
    ) -> Message | None:
        """Latest DRAFT outbound message for a conversation.

        Used by the approve→send wiring (B-11): when an AI suggestion is
        approved the most recent DRAFT outbound message for that conversation
        is the one the human reviewed and consented to send.
        """
        result = await self.session.execute(
            sa.select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.OUTBOUND,
                Message.delivery_status == MessageDeliveryStatus.DRAFT,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------ sync counterparts

    def get_sync(self, message_id: uuid.UUID) -> Message | None:
        """Synchronous get for use in Celery tasks."""
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        return session.get(Message, message_id)

    def get_by_meta_id_sync(self, meta_message_id: str) -> Message | None:
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        return session.execute(
            sa.select(Message).where(Message.meta_message_id == meta_message_id)
        ).scalar_one_or_none()

    def create_sync(self, **kwargs: Any) -> Message:
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        message = Message(**kwargs)
        session.add(message)
        session.flush()
        session.refresh(message)
        return message

    def update_delivery_status_sync(
        self,
        message_id: uuid.UUID,
        new_status: MessageDeliveryStatus,
        *,
        last_error: str | None,
        error_code: int | None = None,
        meta_message_id: str | None = None,
    ) -> None:
        """
        Synchronous version for Celery tasks.
        DB-C4 fix applied identically: last_error always written.
        """
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]

        values: dict[str, Any] = {
            "delivery_status": new_status,
            "last_error": last_error,  # DB-C4 fix: unconditional
            "error_code": error_code,
        }
        if meta_message_id is not None:
            values["meta_message_id"] = meta_message_id

        session.execute(
            sa.update(Message)
            .where(Message.id == message_id)
            .values(**values)
        )

    def increment_retry_sync(self, message_id: uuid.UUID) -> None:
        """
        Synchronous atomic increment for Celery tasks.
        DB-I8 fix applied identically.
        """
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]

        session.execute(
            sa.update(Message)
            .where(Message.id == message_id)
            .values(retry_count=Message.retry_count + 1)  # DB-I8 fix
        )

    def increment_delivery_retry_sync(self, message_id: uuid.UUID) -> None:
        """
        Atomically increment delivery_retry_count.

        Same server-side arithmetic pattern as increment_retry_sync (DB-I8):
        a single UPDATE statement with ``delivery_retry_count + 1``, not a
        read-modify-write.
        """
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]

        session.execute(
            sa.update(Message)
            .where(Message.id == message_id)
            .values(delivery_retry_count=Message.delivery_retry_count + 1)
        )
