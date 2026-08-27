"""Conversation states and lock parameters (DSD §4.2, §4.8)."""

from enum import StrEnum


class ConversationState(StrEnum):
    NEW = "NEW"
    AI_ACTIVE = "AI_ACTIVE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    HUMAN_ASSIGNED = "HUMAN_ASSIGNED"
    AI_PAUSED = "AI_PAUSED"
    CLOSED = "CLOSED"


# Conversation lock timeout (seconds) — DSD §4.8.
LOCK_TIMEOUT_SECONDS: int = 120
