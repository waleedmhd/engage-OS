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
from collections.abc import Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import StateTransitionError, ValidationError
from app.modules.audit.repository import AuditRepository
from app.modules.contacts.repository import ContactRepository
from app.modules.conversations.constants import ConversationState
from app.modules.messaging.constants import (
    MessageDeliveryStatus,
    MessageDirection,
    SenderType,
)
from app.modules.messaging.repository import MessageRepository
from app.modules.messaging.schemas import MessageResponse
from app.modules.templates.constants import TemplateStatus
from app.modules.templates.repository import TemplateRepository

logger = structlog.get_logger(__name__)


class MessagingService:
    def __init__(self, session: AsyncSession) -> None:
        from app.modules.conversations.repository import ConversationRepository  # lazy — cross-module

        self._session = session
        self._msg_repo = MessageRepository(session)
        self._conv_repo = ConversationRepository(session)
        self._audit = AuditRepository(session)

    async def send_message(
        self,
        conversation_id: uuid.UUID,
        content: str,
        actor_id: uuid.UUID,
        *,
        media_asset_id: uuid.UUID | None = None,
        context_message_id: uuid.UUID | None = None,
        msg_type: str | None = None,
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
        from app.modules.media.repository import MediaAssetRepository

        conv = await self._conv_repo.get_or_404(conversation_id)

        if conv.state == ConversationState.CLOSED:
            raise StateTransitionError(
                f"Cannot send message to CLOSED conversation {conversation_id}."
            )

        # Validate context_message_id (reply) if provided.
        if context_message_id is not None:
            ctx_msg = await self._msg_repo.get(context_message_id)
            if ctx_msg is None:
                raise ValidationError(
                    f"context_message_id {context_message_id} does not exist"
                )

        # Resolve message type: explicit override > media-derived > default text.
        resolved_type = msg_type or "text"
        if resolved_type == "text" and media_asset_id is not None:
            media_repo = MediaAssetRepository(self._session)
            media_asset = await media_repo.get(media_asset_id)
            if media_asset is not None:
                resolved_type = media_asset.media_type

        message = await self._msg_repo.create(
            conversation_id=conversation_id,
            direction=MessageDirection.OUTBOUND,
            sender_type=SenderType.AGENT,
            content=content,
            delivery_status=MessageDeliveryStatus.QUEUED,
            msg_type=resolved_type,
            context_message_id=context_message_id,
        )

        # Link media asset to the message.
        if media_asset_id is not None:
            media_repo = MediaAssetRepository(self._session)
            await media_repo.update(media_asset_id, message_id=message.id)

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
        *,
        actor_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[MessageResponse], int]:
        """
        Return paginated messages and the real total count.
        Messages deleted by the requesting agent are excluded.

        Msg-I2 fix: total previously returned len(items) (page size), not
        the actual total. Frontend pagination was permanently broken for
        conversations with more messages than the page limit.
        """
        if isinstance(conversation_id, str):
            conversation_id = uuid.UUID(conversation_id)

        import sqlalchemy as sa
        from sqlalchemy.orm import selectinload

        from app.modules.messaging.models import Message

        stmt_base = sa.select(Message).options(
            selectinload(Message.context_message),
        ).where(Message.conversation_id == conversation_id)

        if actor_id is not None:
            stmt_base = stmt_base.where(
                sa.or_(
                    Message.deleted_by.is_(None),
                    Message.deleted_by.op('->>')('agent_id').is_(None),
                    Message.deleted_by.op('->>')('agent_id') != str(actor_id),
                )
            )

        stmt = stmt_base.order_by(Message.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        # DESC order returns newest first; reverse for oldest-first display
        items = list(reversed(rows))

        count_stmt = sa.select(sa.func.count()).select_from(
            stmt_base.subquery()
        )
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one()

        return (
            [MessageResponse.model_validate(m) for m in items],
            total,
        )

    async def forward_message(
        self,
        message_id: uuid.UUID,
        target_conversation_id: uuid.UUID,
        actor_id: uuid.UUID,
    ):
        """Copy a message to a target conversation, setting context_message_id
        to point back to the source message so the frontend renders it as a
        forwarded message."""
        source = await self._msg_repo.get_or_404(message_id)
        target = await self._conv_repo.get_or_404(target_conversation_id)

        if target.state == ConversationState.CLOSED:
            raise StateTransitionError(
                f"Cannot forward to CLOSED conversation {target_conversation_id}."
            )

        # Resolve msg_type for the forwarded copy. If the source was a media
        # message, keep its type. Forwarded text bodies use the source content.
        forwarded = await self._msg_repo.create(
            conversation_id=target_conversation_id,
            direction=MessageDirection.OUTBOUND,
            sender_type=SenderType.AGENT,
            content=source.content,
            delivery_status=MessageDeliveryStatus.QUEUED,
            msg_type=source.msg_type,
            context_message_id=source.id,
        )

        # If the source had media, copy the media asset reference too so the
        # forwarded bubble renders the same media.
        if source.msg_type != "text":
            from app.modules.media.repository import MediaAssetRepository

            media_repo = MediaAssetRepository(self._session)
            source_assets = await media_repo.get_by_message_id(source.id)
            if source_assets:
                # Point the first asset at the forwarded message.
                await media_repo.update(
                    source_assets[0].id, message_id=forwarded.id
                )

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,
            action="message.forwarded",
            entity_type="message",
            entity_id=forwarded.id,
            before_state=None,
            after_state={
                "source_message_id": str(source.id),
                "target_conversation_id": str(target_conversation_id),
            },
        )

        logger.info(
            "message_forwarded",
            source_message_id=str(message_id),
            target_conversation_id=str(target_conversation_id),
            new_message_id=str(forwarded.id),
            actor_id=str(actor_id),
        )

        await self._session.flush()
        return forwarded

    async def bulk_forward(
        self,
        *,
        message_ids: list[uuid.UUID],
        target_conversation_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> tuple[int, list[str], list[uuid.UUID]]:
        """Forward multiple messages to a target conversation.
        Returns (count, errors, forwarded_message_ids)."""
        target = await self._conv_repo.get_or_404(target_conversation_id)

        if target.state == ConversationState.CLOSED:
            raise StateTransitionError(
                f"Cannot forward to CLOSED conversation {target_conversation_id}."
            )

        count = 0
        errors: list[str] = []
        forwarded_ids: list[uuid.UUID] = []
        for mid in message_ids:
            try:
                fwd = await self.forward_message(mid, target_conversation_id, actor_id)
                count += 1
                forwarded_ids.append(fwd.id)
            except Exception as exc:
                errors.append(f"Message {mid}: {exc}")

        logger.info(
            "messages_bulk_forwarded",
            count=count,
            errors_count=len(errors),
            target_conversation_id=str(target_conversation_id),
            actor_id=str(actor_id),
        )

        return count, errors, forwarded_ids

    async def bulk_delete(
        self,
        *,
        message_ids: list[uuid.UUID],
        scope: str,
        actor_id: uuid.UUID,
    ) -> tuple[int, list[str]]:
        """Soft-delete messages. scope='for_me' marks deleted_by for the agent;
        scope='for_everyone' sets deleted_for_everyone=true and returns the
        message IDs that need a Meta delete API call."""
        import datetime

        now = datetime.datetime.now(datetime.UTC).isoformat()
        count = 0
        errors: list[str] = []

        for mid in message_ids:
            try:
                msg = await self._msg_repo.get_or_404(mid)
                values: dict = {}
                if scope == "for_everyone":
                    values["deleted_for_everyone"] = True
                    # Also mark agent-side delete
                    existing = msg.deleted_by or {}
                    existing["agent_id"] = now
                    values["deleted_by"] = existing
                else:
                    existing = msg.deleted_by or {}
                    existing["agent_id"] = now
                    values["deleted_by"] = existing

                await self._msg_repo.update(mid, **values)
                count += 1
            except Exception as exc:
                errors.append(f"Message {mid}: {exc}")

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,
            action="messages.bulk_deleted",
            entity_type="message",
            entity_id=None,
            before_state=None,
            after_state={
                "count": count,
                "scope": scope,
                "message_ids": [str(mid) for mid in message_ids],
            },
        )

        logger.info(
            "messages_bulk_deleted",
            count=count,
            scope=scope,
            errors_count=len(errors),
            actor_id=str(actor_id),
        )

        await self._session.flush()
        return count, errors

    async def start_conversation_with_template(
        self,
        *,
        contact_id: uuid.UUID,
        template_id: uuid.UUID,
        actor_id: uuid.UUID,
    ):
        """Initiate an outbound conversation with a contact using an approved template.

        Implements the "New message" flow (plan §3):
          1. Validate the template exists and is APPROVED.
          2. Get or create an open conversation for the contact.
          3. Persist an OUTBOUND QUEUED message with template_name/language set
             so the dispatch task uses Meta's send_template API.

        Returns (conversation, message). The router commits then dispatches
        send_outbound_message_task (Msg-C4 pattern).
        """
        # 1. Load & validate contact (raises NotFoundError → 404).
        contact_repo = ContactRepository(self._session)
        await contact_repo.get_or_404(contact_id)

        # 2. Load & validate template.
        template_repo = TemplateRepository(self._session)
        template = await template_repo.get_or_404(template_id)
        if template.status != TemplateStatus.APPROVED.value:
            raise ValidationError(
                f"Template '{template.name}' is not approved "
                f"(status: {template.status}). Only APPROVED templates may be "
                "used to initiate a conversation."
            )

        # 3. Reuse any open conversation, or create a fresh one.
        conv = await self._conv_repo.get_open_for_contact(contact_id)
        if conv is None:
            conv = await self._conv_repo.create_for_contact(contact_id=contact_id)

        # 4. Persist the outbound message, carrying template identity so the
        #    dispatch task calls send_template instead of send_text.
        message = await self._msg_repo.create(
            conversation_id=conv.id,
            direction=MessageDirection.OUTBOUND,
            sender_type=SenderType.AGENT,
            # content must not be NULL; use the template name as a readable label.
            content=template.name,
            delivery_status=MessageDeliveryStatus.QUEUED,
            template_name=template.name,
            template_language=template.language,
        )

        await self._audit.append(
            actor_type="agent",
            actor_id=actor_id,
            action="message.outbound_queued",
            entity_type="message",
            entity_id=message.id,
            before_state=None,
            after_state={
                "delivery_status": MessageDeliveryStatus.QUEUED.value,
                "template_name": template.name,
            },
        )

        logger.info(
            "template_conversation_started",
            conversation_id=str(conv.id),
            contact_id=str(contact_id),
            template_name=template.name,
            actor_id=str(actor_id),
        )

        await self._session.flush()
        return conv, message
