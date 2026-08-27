"""
app/core/events.py

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

import structlog
from typing import Any, Callable

logger = structlog.get_logger(__name__)

# Handler type: (event_name: str, **payload) -> None
EventHandler = Callable[..., None]

_subscribers: dict[str, list[EventHandler]] = {}


def subscribe(event_name: str, handler: EventHandler) -> None:
    """Register a handler to be called when event_name is emitted."""
    _subscribers.setdefault(event_name, []).append(handler)


def unsubscribe(event_name: str, handler: EventHandler) -> None:
    """Deregister a previously registered handler. No-op if not found."""
    if event_name in _subscribers:
        try:
            _subscribers[event_name].remove(handler)
        except ValueError:
            pass


def emit_event(event_name: str, **payload: Any) -> None:
    """
    Emit a domain event to all registered subscribers.

    Conv-C5 fix: structlog reserves the `event` keyword for its own message
    binding. Passing event=<our_event_name> raised:
        TypeError: event() got an unexpected keyword argument 'event'
    on every call. Every state transition emits at least one domain event,
    so the entire conversation engine produced HTTP 500 in production.

    The fix is straightforward:
      - Pass the log message as a positional string (structlog's `event`).
      - Pass our domain event name as `event_name=` (no collision).
    """
    logger.info(
        "domain_event_emitted",   # ← positional str; structlog binds as `event`
        event_name=event_name,    # ← our field; no reserved kwarg collision
        **payload,
    )
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
    else:
        _subscribers.pop(event_name, None)


# ------------------------------------------------------------------ Event names
# Centralised string constants prevent typos across modules.
# Expand here as new domains are added; keep alphabetical within domain.

class ConversationEvents:
    AI_PAUSED = "conversation.ai_paused"
    AI_RESUMED = "conversation.ai_resumed"
    APPROVED = "conversation.approved"
    ASSIGNED = "conversation.assigned"
    CLOSED = "conversation.closed"
    CREATED = "conversation.created"
    ESCALATED = "conversation.escalated"
    FIRST_ACTIVATED = "conversation.first_activated"  # NEW → AI_ACTIVE
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
