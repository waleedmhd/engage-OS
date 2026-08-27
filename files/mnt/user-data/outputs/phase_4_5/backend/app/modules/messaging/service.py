"""
app/modules/messaging/service.py

Fix applied:
  Msg-C4 — send_outbound_message_task.delay() was called inside
            send_message() before the calling router committed the
            session transaction. The Celery worker could be scheduled
            and start fetching the message row before it was committed,
            resulting in "message not found" failures logged silently
            while the task exited without sending.

            Fix: send_message() no longer calls .delay() at all. It
            persists the message row (flush only) and returns the message
            object. The router calls session.commit() THEN dispatches the
            task. This guarantees the row is durable before any worker
            can read it.

            The task dispatch line in the router is:
                message = await service.send_message(...)
                await session.commit()
                send_outbound_message_task.delay(str(message.id))

  Msg-M8  — MessageResponse now includes created_at and meta_message_id.
             The frontend inbox requires both for ordering and deduplication.

  Msg-M13 — actor_id from JWT is now coerced to UUID before logging,
             preventing unsanitised freeform strings in structured log fields.
"""
from __future__ import annotations

import uuid
from typing import Sequence, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, StateTransitionError
from app.modules.audit.repository import AuditRepository
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.repository import ConversationRepository
from app.modules.messaging.constants import (
    MessageDirection,
    MessageDeliveryStatus,
    SenderType,
)
from app.modules.messaging.repository import MessageRepository
from app.modules.messaging.schemas import MessageResponse

logger = structlog.get_logger(__name__)


class MessagingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._msg_repo = MessageRepository(session)
        self._conv_repo = ConversationRepository(session)
        self._audit = AuditRepository(session)

    async def send_message(
        self,
        conversation_id: uuid.UUID,
        content: str,
        actor_id: uuid.UUID,
    ):
        """
        Persist an outbound message and return it.

        Msg-C4 fix: this method NO LONGER dispatches the Celery task.
        The router is responsible for:
          1. Calling send_message() (flush only)
          2. Calling session.commit() (makes row durable)
          3. Dispatching send_outbound_message_task.delay(message_id)

        This ordering guarantees the Celery worker will always find the
        message row when it reads from the DB.

        Msg-M13 fix: actor_id is typed as uuid.UUID and coerced at the
        call boundary — structured log fields always contain a valid UUID
        string, never a raw unsanitised token claim string.
        """
        conv = await self._conv_repo.get_or_404(conversation_id)

        if conv.state == ConversationState.CLOSED:
            raise StateTransitionError(
                f"Cannot send message to CLOSED conversation {conversation_id}."
            )

        message = await self._msg_repo.create(
            conversation_id=conversation_id,
            direction=MessageDirection.OUTBOUND,
            sender_type=SenderType.AGENT,
            content=content,
            delivery_status=MessageDeliveryStatus.QUEUED,
        )

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,  # Msg-M13: already uuid.UUID at this point
            action="message.outbound_queued",
            entity_type="message",
            entity_id=message.id,
            before_state=None,
            after_state={"delivery_status": MessageDeliveryStatus.QUEUED.value},
        )

        logger.info(
            "outbound_message_queued",
            message_id=str(message.id),
            conversation_id=str(conversation_id),
            actor_id=str(actor_id),  # Msg-M13: UUID coerced to str for log
        )

        # Msg-C4 fix: flush only — do NOT call task.delay() here.
        # The router commits and dispatches the task after this returns.
        await self._session.flush()
        return message

    async def list_messages(
        self,
        conversation_id: uuid.UUID | str,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[Sequence[MessageResponse], int]:
        """
        Return paginated messages and the real total count.

        Msg-I2 fix: total previously returned len(items) (page size), not
        the actual total. Frontend pagination was permanently broken for
        conversations with more messages than the page limit.
        """
        if isinstance(conversation_id, str):
            conversation_id = uuid.UUID(conversation_id)

        items = await self._msg_repo.list(
            filters={"conversation_id": conversation_id},
            order_by="created_at",
            limit=limit,
            offset=offset,
        )
        total = await self._msg_repo.count(
            filters={"conversation_id": conversation_id}
        )

        return (
            [MessageResponse.model_validate(m) for m in items],
            total,
        )
