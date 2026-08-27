"""
app/core/events.py

In-process domain event bus. Sync handlers for fire-and-forget events (CRM);
async handlers for transactional bridge subscribers (ERP — must complete before
the caller's transaction commits).

Fix applied:
  Conv-C5 — structlog's positional message argument IS the reserved `event`
             kwarg. The previous code called:
               logger.info("event_emitted", event=event, ...)
             which collided with structlog's internal event binding and raised
             TypeError on every state transition. All production paths through
             the conversation engine 500'd. Tests monkeypatched around it.

             Fix: the human-readable log message is passed as the first
             positional argument (structlog binds it internally as `event`).
             Our domain event name travels as `event_name=` — no collision.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Handler type: (event_name: str, **payload) -> None
EventHandler = Callable[..., None]
# Async handler: (event_name: str, **payload) -> Awaitable[None]
AsyncEventHandler = Callable[..., Awaitable[None]]

_subscribers: dict[str, list[EventHandler]] = {}
_async_subscribers: dict[str, list[Any]] = {}

# ----------------------------------------------------- cross-process fan-out
# P2.1 (live inbox WebSocket, DSD §7.2 / §10 "<2s dashboard update").
#
# The in-process subscriber list above only reaches handlers in the SAME
# process. Inbound messages are persisted by Celery WORKER processes, but the
# WebSocket that the dashboard connects to lives in an API process. To bridge
# that gap every inbox-relevant domain event is also PUBLISHED to a Redis
# pub/sub channel; the `/ws/inbox` handler in app.main subscribes to it and
# relays JSON frames to authenticated clients.
INBOX_PUBSUB_CHANNEL = "events:inbox"
_RELAYED_EVENT_PREFIXES = ("message.", "conversation.")


def _publish_to_pubsub(event_name: str, payload: dict[str, Any]) -> None:
    """Best-effort publish of an inbox-relevant event to Redis pub/sub.

    Never raises: the domain write that triggered this event has already
    been committed; a Redis failure here must not propagate.
    """
    if not event_name.startswith(_RELAYED_EVENT_PREFIXES):
        return
    try:
        from app.core.redis import get_sync_redis

        frame = json.dumps({"event": event_name, **payload}, default=str)
        get_sync_redis().publish(INBOX_PUBSUB_CHANNEL, frame)
    except Exception:
        logger.warning(
            "inbox_event_publish_failed",
            event_name=event_name,
            exc_info=True,
        )


def subscribe(event_name: str, handler: EventHandler) -> None:
    """Register a sync handler to be called when event_name is emitted."""
    _subscribers.setdefault(event_name, []).append(handler)


def unsubscribe(event_name: str, handler: EventHandler) -> None:
    """Deregister a previously registered handler. No-op if not found."""
    if event_name in _subscribers:
        try:
            _subscribers[event_name].remove(handler)
        except ValueError:
            pass


def subscribe_async(event_name: str, handler: AsyncEventHandler) -> None:
    """Register an async handler (used by ERP bridge subscribers)."""
    lst: list[AsyncEventHandler] = _async_subscribers.setdefault(event_name, [])
    lst.append(handler)


def unsubscribe_async(event_name: str, handler: AsyncEventHandler) -> None:
    if event_name in _async_subscribers:
        try:
            _async_subscribers[event_name].remove(handler)
        except ValueError:
            pass


def emit_event(event_name: str, **payload: Any) -> None:
    """
    Emit a domain event to all registered sync subscribers.

    Conv-C5 fix: structlog reserves the `event` keyword for its own message
    binding. Passing event=<our_event_name> raised:
        TypeError: event() got an unexpected keyword argument 'event'
    on every call.

    The fix:
      - Pass the log message as a positional string (structlog's `event`).
      - Pass our domain event name as `event_name=` (no collision).
    """
    logger.info(
        "domain_event_emitted",
        event_name=event_name,
        **payload,
    )

    _publish_to_pubsub(event_name, payload)

    for handler in list(_subscribers.get(event_name, [])):
        try:
            handler(event_name, **payload)
        except Exception:
            logger.exception(
                "domain_event_handler_error",
                event_name=event_name,
                handler=getattr(handler, "__qualname__", repr(handler)),
            )


async def emit_event_async(event_name: str, **payload: Any) -> None:
    """
    Emit a domain event and await all registered async handlers.

    Used by ERP bridge: the caller (procurement/fulfilment/inventory) passes
    its session in the payload so the bridge handler posts journals in the
    same transaction. The caller MUST await this function.
    """
    logger.info(
        "domain_event_emitted_async",
        event_name=event_name,
        **payload,
    )

    for handler in list(_async_subscribers.get(event_name, [])):
        try:
            await handler(event_name, **payload)
        except Exception:
            logger.exception(
                "domain_event_handler_error",
                event_name=event_name,
                handler=getattr(handler, "__qualname__", repr(handler)),
            )

    # Also run sync subscribers for this event (backwards-compat).
    for handler in list(_subscribers.get(event_name, [])):
        try:
            handler(event_name, **payload)
        except Exception:
            logger.exception(
                "domain_event_handler_error",
                event_name=event_name,
                handler=getattr(handler, "__qualname__", repr(handler)),
            )


def clear_subscribers(event_name: str | None = None) -> None:
    """
    Remove all handlers. Intended for use in tests only — call in teardown
    to prevent subscriber bleed between test cases.
    """
    if event_name is None:
        _subscribers.clear()
        _async_subscribers.clear()
    else:
        _subscribers.pop(event_name, None)
        _async_subscribers.pop(event_name, None)


# ------------------------------------------------------------------ Event names
# Centralised string constants prevent typos across modules.
# Expand here as new domains are added; keep alphabetical within domain.

# Event name constants.
#
# These classes are defined here for backward compatibility — every existing
# import site uses ``from app.core.events import ConversationEvents`` etc.
# Domain modules have their own ``events.py`` as the canonical home for new
# event names, but we keep local definitions here to avoid circular imports
# (several domain modules import from ``app.core.events`` at module level,
# so re-exporting from domain modules would create cycles).


class ConversationEvents:
    AI_PAUSED = "conversation.ai_paused"
    AI_RESUMED = "conversation.ai_resumed"
    APPROVED = "conversation.approved"
    ASSIGNED = "conversation.assigned"
    CLOSED = "conversation.closed"
    CREATED = "conversation.created"
    ESCALATED = "conversation.escalated"
    FIRST_ACTIVATED = "conversation.first_activated"
    LOCK_EXPIRED = "conversation.lock_expired"
    REJECTED = "conversation.rejected"


class MessageEvents:
    DELIVERED = "message.delivered"
    FAILED = "message.failed"
    READ = "message.read"
    RECEIVED = "message.received"
    SENT = "message.sent"


class TagEvents:
    APPROVED = "tag.approved"
    REJECTED = "tag.rejected"
    SUGGESTED = "tag.suggested"


class CampaignEvents:
    COMPLETED = "campaign.completed"
    FAILED = "campaign.failed"
    LAUNCHED = "campaign.launched"


class InventoryEvents:
    """ERP inventory events consumed by the ledger bridge (async subscribers)."""
    GRN_CONFIRMED = "inventory.grn_confirmed"
    UNIT_DISPATCHED = "inventory.unit_dispatched"
    ADJUSTMENT_CONFIRMED = "inventory.adjustment_confirmed"


class FinanceEvents:
    """ERP finance events."""
    ENTRY_POSTED = "ledger.entry_posted"
    INVOICE_CREATED = "finance.invoice_created"
    BILL_MATCHED = "payables.bill_matched"
    PERIOD_CLOSED = "ledger.period_closed"
    PERIOD_REOPENED = "ledger.period_reopened"
