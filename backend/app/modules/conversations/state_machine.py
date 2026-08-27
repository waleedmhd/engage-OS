"""Conversation state machine (DSD §4.2).

Encodes the legal transition graph and guard predicates. Pure functions, no
I/O — the service layer composes these with persistence and audit.
"""

from __future__ import annotations

from app.core.events import ConversationEvents
from app.core.exceptions import ConflictError, ValidationError
from app.modules.conversations.constants import ConversationState

# Legal transitions per DSD §4.2.
#
# DSD §4.2 enumerates the "happy path" transitions; CLOSED is a terminal sink
# reachable from any non-terminal state (the DSD lists CLOSED as a state but
# does not constrain its predecessors, and CRM conversations must be closeable
# from any live state). All other arcs below are explicit DSD §4.2 rules.
_ALLOWED: dict[ConversationState, frozenset[ConversationState]] = {
    ConversationState.NEW: frozenset(
        {
            ConversationState.AI_ACTIVE,         # inbound message arrived
            ConversationState.HUMAN_ASSIGNED,    # admin pre-assigns
            ConversationState.CLOSED,
        }
    ),
    ConversationState.AI_ACTIVE: frozenset(
        {
            ConversationState.AWAITING_APPROVAL,  # AI proposes action
            ConversationState.HUMAN_ASSIGNED,     # escalation
            ConversationState.AI_PAUSED,          # human replies manually
            ConversationState.CLOSED,
        }
    ),
    ConversationState.AWAITING_APPROVAL: frozenset(
        {
            ConversationState.AI_ACTIVE,        # approved → AI continues
            ConversationState.HUMAN_ASSIGNED,   # rejected → escalate
            ConversationState.AI_PAUSED,        # human takes over
            ConversationState.CLOSED,
        }
    ),
    ConversationState.HUMAN_ASSIGNED: frozenset(
        {
            ConversationState.AI_PAUSED,        # agent done, hands back paused
            ConversationState.AI_ACTIVE,        # agent releases, AI resumes
            ConversationState.CLOSED,
        }
    ),
    ConversationState.AI_PAUSED: frozenset(
        {
            ConversationState.AI_ACTIVE,        # manual resume — DSD §4.2
            ConversationState.HUMAN_ASSIGNED,   # assign while paused
            ConversationState.CLOSED,
        }
    ),
    ConversationState.CLOSED: frozenset(),       # terminal
}


TERMINAL_STATES: frozenset[ConversationState] = frozenset({ConversationState.CLOSED})


# Phase 4.5 (Conv-I5 + service refactor): the transition→event-name map moved
# from the service module up to the state machine so audit logs and domain
# events derive from a single source of truth. ConversationService imports this.
TRANSITION_EVENTS: dict[tuple[ConversationState, ConversationState], str] = {
    (ConversationState.NEW, ConversationState.AI_ACTIVE): ConversationEvents.FIRST_ACTIVATED,
    (ConversationState.NEW, ConversationState.HUMAN_ASSIGNED): ConversationEvents.ASSIGNED,
    (ConversationState.NEW, ConversationState.CLOSED): ConversationEvents.CLOSED,
    (ConversationState.AI_ACTIVE, ConversationState.AI_PAUSED): ConversationEvents.AI_PAUSED,
    (ConversationState.AI_ACTIVE, ConversationState.AWAITING_APPROVAL): ConversationEvents.ESCALATED,
    (ConversationState.AI_ACTIVE, ConversationState.HUMAN_ASSIGNED): ConversationEvents.ASSIGNED,
    (ConversationState.AI_ACTIVE, ConversationState.CLOSED): ConversationEvents.CLOSED,
    (ConversationState.AWAITING_APPROVAL, ConversationState.AI_ACTIVE): ConversationEvents.APPROVED,
    (ConversationState.AWAITING_APPROVAL, ConversationState.AI_PAUSED): ConversationEvents.AI_PAUSED,
    (ConversationState.AWAITING_APPROVAL, ConversationState.HUMAN_ASSIGNED): ConversationEvents.REJECTED,
    (ConversationState.AWAITING_APPROVAL, ConversationState.CLOSED): ConversationEvents.CLOSED,
    (ConversationState.HUMAN_ASSIGNED, ConversationState.AI_ACTIVE): ConversationEvents.AI_RESUMED,
    (ConversationState.HUMAN_ASSIGNED, ConversationState.AI_PAUSED): ConversationEvents.AI_PAUSED,
    (ConversationState.HUMAN_ASSIGNED, ConversationState.CLOSED): ConversationEvents.CLOSED,
    (ConversationState.AI_PAUSED, ConversationState.AI_ACTIVE): ConversationEvents.AI_RESUMED,
    (ConversationState.AI_PAUSED, ConversationState.HUMAN_ASSIGNED): ConversationEvents.ASSIGNED,
    (ConversationState.AI_PAUSED, ConversationState.CLOSED): ConversationEvents.CLOSED,
}


def can_transition(current: ConversationState, target: ConversationState) -> bool:
    """Return True iff `current → target` is a legal arc."""
    return target in _ALLOWED.get(current, frozenset())


def allowed_transitions(current: ConversationState) -> frozenset[ConversationState]:
    return _ALLOWED.get(current, frozenset())


def assert_transition(current: ConversationState, target: ConversationState) -> None:
    """Raise on illegal transitions.

    - Same-state no-ops are rejected as ValidationError (callers should not
      ask the engine to do nothing).
    - Terminal-state moves are rejected as ConflictError (CLOSED is final).
    - Other illegal arcs are ValidationError.
    """
    if current in TERMINAL_STATES:
        raise ConflictError(
            "conversation_closed",
            details={"from": current.value, "to": target.value},
        )
    if current == target:
        raise ValidationError(
            "invalid_transition",
            details={"from": current.value, "to": target.value, "reason": "noop"},
        )
    if not can_transition(current, target):
        raise ValidationError(
            "invalid_transition",
            details={
                "from": current.value,
                "to": target.value,
                "allowed": sorted(s.value for s in allowed_transitions(current)),
            },
        )


def coerce(state: str | ConversationState) -> ConversationState:
    """Accept either the enum or its string value (DB rows store the str)."""
    if isinstance(state, ConversationState):
        return state
    try:
        return ConversationState(state)
    except ValueError as exc:
        raise ValidationError(
            "unknown_state", details={"state": state}
        ) from exc
