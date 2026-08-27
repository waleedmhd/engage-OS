"""Conversation domain events published to the event bus."""


class ConversationEvents:
    AI_PAUSED = "conversation.ai_paused"
    AI_RESUMED = "conversation.ai_resumed"
    APPROVED = "conversation.approved"
    ASSIGNED = "conversation.assigned"
    CLOSED = "conversation.closed"
    CREATED = "conversation.created"
    ESCALATED = "conversation.escalated"
    FIRST_ACTIVATED = "conversation.first_activated"  # NEW → AI_ACTIVE
    LOCK_EXPIRED = "conversation.lock_expired"
    REJECTED = "conversation.rejected"
