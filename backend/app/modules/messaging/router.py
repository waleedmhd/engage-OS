"""
app/modules/messaging/router.py

Fix applied:
  Msg-C3 — When META_APP_SECRET was empty, the original signature
            verification code silently skipped verification entirely and
            accepted any POST as valid. There was no ENV gate — a
            misconfigured production deployment would accept unsigned
            or forged requests from any source.

            Fix: if META_APP_SECRET is empty and ENV is not development,
            the request is rejected with HTTP 403 before any payload
            processing begins. This is the fail-closed posture: a
            misconfiguration is surfaced as an operational error
            (which can be spotted and fixed) rather than silently
            accepting unauthenticated webhooks.

            In development, an empty secret is still accepted (bypasses
            verification) to ease local testing without a real Meta app.

  Msg-M5  — Returning 401 on bad signature caused Meta to immediately
            retry, creating a retry storm. Fix: return 200 for
            signature mismatches to stop Meta retrying, but log the
            event as a security warning. This is the Meta-recommended
            posture for malformed-but-non-malicious payloads.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user_db, get_db_session
from app.modules.messaging.schemas import (
    BulkActionResponse,
    BulkDeleteRequest,
    BulkForwardRequest,
    ForwardMessageRequest,
    MessageListResponse,
    MessageResponse,
    SendMessageRequest,
    SendMessageResponse,
    StartConversationRequest,
    StartConversationResponse,
)
from app.modules.messaging.service import MessagingService
from app.modules.messaging.tasks import process_inbound_webhook_task

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
messages_router = APIRouter(prefix="/messages", tags=["messages"])


# ----------------------------------------------------------- webhook endpoints

@router.get("/meta")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
) -> int:
    """Meta webhook GET handshake."""
    settings = get_settings()
    if hub_mode != "subscribe" or hub_verify_token != settings.META_VERIFY_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify token mismatch.",
        )
    return int(hub_challenge)


@router.post("/meta", status_code=status.HTTP_200_OK)
async def receive_meta_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    """
    Receive Meta webhook events.

    Msg-C3 fix: fail closed when META_APP_SECRET is not configured in
    non-development environments. Previously an empty secret silently
    bypassed all signature verification.

    Msg-M5 fix: return HTTP 200 on signature mismatch (with a warning
    log) to avoid triggering Meta's retry mechanism on what may be a
    misconfigured but non-malicious request. Only genuine security
    events (missing secret in prod) return 403.
    """
    settings = get_settings()
    raw_body = await request.body()

    # Msg-C3 fix: fail closed if secret is missing in non-development.
    if not settings.META_APP_SECRET:
        if settings.ENV != "development":
            logger.error(
                "meta_webhook_misconfiguration",
                reason="META_APP_SECRET is empty in non-development environment",
                env=settings.ENV,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Webhook signature verification is not configured. "
                    "Set META_APP_SECRET in environment variables."
                ),
            )
        # Development-only: proceed without verification (local testing).
        logger.warning(
            "meta_webhook_signature_skipped",
            reason="META_APP_SECRET not set — skipping verification in development",
        )
    else:
        # Verify HMAC-SHA256 signature.
        if not _verify_signature(
            raw_body,
            settings.META_APP_SECRET,
            x_hub_signature_256,
        ):
            # Msg-M5 fix: return 200 + log warning instead of 401.
            # Returning 401 triggers Meta's automatic retry with exponential
            # backoff — a retry storm for a single bad request. 200 stops
            # the retry loop; the warning surfaces in monitoring.
            logger.warning(
                "meta_webhook_signature_invalid",
                signature_header=x_hub_signature_256,
                body_length=len(raw_body),
            )
            return {"status": "ignored"}

    # Prefetch media onto the API process's filesystem BEFORE dispatching to
    # the Celery worker, so the serve-media endpoint can find the files later.
    # Inlined import avoids coupling the router module to the tasks module at
    # import time (Celery app init).
    payload: dict[str, Any] = await request.json()

    import asyncio

    from app.modules.messaging.tasks import prefetch_inbound_media

    await asyncio.to_thread(prefetch_inbound_media, payload)

    process_inbound_webhook_task.delay(payload)

    return {"status": "ok"}


def _verify_signature(
    body: bytes,
    secret: str,
    signature_header: str | None,
) -> bool:
    """
    Verify the X-Hub-Signature-256 header against the request body.

    Returns False (rather than raising) so the caller can decide the
    response strategy (log and return 200 vs hard reject).
    """
    if not signature_header:
        return False

    if not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


# ----------------------------------------------------------- message endpoints

@messages_router.post("/send", response_model=SendMessageResponse)
async def send_message(
    payload: SendMessageRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> SendMessageResponse:
    """
    Send an outbound message from an agent.

    Msg-C4 fix: the Celery task is dispatched AFTER session.commit().
    Previously the task was fired inside the service method, before the
    router committed the transaction. The Celery worker could start
    processing (and fail to find the message row) before it was committed.
    """
    service = MessagingService(session)
    message = await service.send_message(
        conversation_id=payload.conversation_id,
        content=payload.content,
        actor_id=current_user.id,
        media_asset_id=payload.media_asset_id,
        context_message_id=payload.context_message_id,
        msg_type=payload.msg_type,
    )
    # Msg-C4 fix: commit first, then dispatch task.
    # The message row is now durable before the worker is invoked.
    await session.commit()

    from app.modules.messaging.tasks import send_outbound_message_task
    send_outbound_message_task.delay(str(message.id))

    return SendMessageResponse.model_validate(message)


@messages_router.post("/start", response_model=StartConversationResponse, status_code=status.HTTP_201_CREATED)
async def start_conversation(
    payload: StartConversationRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> StartConversationResponse:
    """Initiate an outbound conversation with a contact via an approved WhatsApp template.

    Follows Msg-C4 ordering: commit before dispatching the Celery task so the
    worker always finds the message row. Reuses an existing open conversation
    for the contact rather than creating a duplicate thread.
    """
    service = MessagingService(session)
    conv, message = await service.start_conversation_with_template(
        contact_id=payload.contact_id,
        template_id=payload.template_id,
        actor_id=current_user.id,
    )
    await session.commit()

    from app.modules.messaging.tasks import send_outbound_message_task
    send_outbound_message_task.delay(str(message.id))

    return StartConversationResponse(
        conversation_id=conv.id,
        message=MessageResponse.model_validate(message),
    )


@messages_router.post("/{message_id}/forward", response_model=SendMessageResponse)
async def forward_message(
    message_id: str,
    payload: ForwardMessageRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> SendMessageResponse:
    """Forward a message to another active conversation."""
    service = MessagingService(session)
    message = await service.forward_message(
        message_id=uuid.UUID(message_id),
        target_conversation_id=payload.target_conversation_id,
        actor_id=current_user.id,
    )
    await session.commit()

    from app.modules.messaging.tasks import send_outbound_message_task
    send_outbound_message_task.delay(str(message.id))

    return SendMessageResponse.model_validate(message)


@messages_router.get("/{conversation_id}", response_model=MessageListResponse)
async def list_messages(
    conversation_id: str,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> MessageListResponse:
    service = MessagingService(session)
    items, total = await service.list_messages(
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
        actor_id=current_user.id,
    )
    return MessageListResponse(items=list(items), total=total)


@messages_router.post("/bulk-forward", response_model=BulkActionResponse)
async def bulk_forward(
    payload: BulkForwardRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> BulkActionResponse:
    """Forward multiple messages to another active conversation."""
    service = MessagingService(session)
    count, errors, fwd_ids = await service.bulk_forward(
        message_ids=payload.message_ids,
        target_conversation_id=payload.target_conversation_id,
        actor_id=current_user.id,
    )
    await session.commit()

    from app.modules.messaging.tasks import send_outbound_message_task
    for fwd_id in fwd_ids:
        send_outbound_message_task.delay(str(fwd_id))

    return BulkActionResponse(count=count, errors=errors)


@messages_router.post("/bulk-delete", response_model=BulkActionResponse)
async def bulk_delete(
    payload: BulkDeleteRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user_db),
) -> BulkActionResponse:
    """Soft-delete messages for the agent or for everyone."""
    service = MessagingService(session)
    count, errors = await service.bulk_delete(
        message_ids=payload.message_ids,
        scope=payload.scope,
        actor_id=current_user.id,
    )
    await session.commit()

    # For "delete for everyone", dispatch Meta delete API calls via Celery.
    if payload.scope == "for_everyone":
        from app.modules.messaging.tasks import request_meta_deletion_task
        for mid in payload.message_ids:
            request_meta_deletion_task.delay(str(mid))

    return BulkActionResponse(count=count, errors=errors)
