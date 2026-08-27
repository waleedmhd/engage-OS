"""Unit tests for the conversation state machine engine.

Pure-function tests — no DB, no service, no fixtures beyond pytest.
"""

import pytest

from app.core.exceptions import ConflictError, ValidationError
from app.modules.conversations.constants import ConversationState as S
from app.modules.conversations.state_machine import (
    allowed_transitions,
    assert_transition,
    can_transition,
    coerce,
)

# DSD §4.2 explicit arcs.
DSD_ARCS = [
    (S.NEW, S.AI_ACTIVE),
    (S.AI_ACTIVE, S.AWAITING_APPROVAL),
    (S.AI_ACTIVE, S.HUMAN_ASSIGNED),
    (S.AI_ACTIVE, S.AI_PAUSED),
    (S.AI_PAUSED, S.AI_ACTIVE),
]


@pytest.mark.parametrize("src,dst", DSD_ARCS)
def test_dsd_arcs_are_legal(src, dst):
    assert can_transition(src, dst) is True
    assert_transition(src, dst)  # does not raise


def test_closed_is_terminal():
    for state in S:
        assert can_transition(S.CLOSED, state) is False
    assert allowed_transitions(S.CLOSED) == frozenset()


def test_closed_is_reachable_from_every_live_state():
    for state in S:
        if state is S.CLOSED:
            continue
        assert can_transition(state, S.CLOSED) is True


def test_terminal_transition_raises_conflict():
    with pytest.raises(ConflictError, match="conversation_closed"):
        assert_transition(S.CLOSED, S.AI_ACTIVE)


def test_same_state_is_invalid():
    with pytest.raises(ValidationError, match="invalid_transition"):
        assert_transition(S.AI_ACTIVE, S.AI_ACTIVE)


def test_illegal_arc_raises_validation_with_allowed_list():
    # NEW → AWAITING_APPROVAL is not legal (must pass through AI_ACTIVE first).
    with pytest.raises(ValidationError) as exc_info:
        assert_transition(S.NEW, S.AWAITING_APPROVAL)
    details = exc_info.value.details
    assert details["from"] == "NEW"
    assert details["to"] == "AWAITING_APPROVAL"
    assert "AI_ACTIVE" in details["allowed"]


def test_coerce_accepts_enum_and_string():
    assert coerce(S.AI_ACTIVE) is S.AI_ACTIVE
    assert coerce("AI_ACTIVE") is S.AI_ACTIVE


def test_coerce_rejects_unknown_state():
    with pytest.raises(ValidationError, match="unknown_state"):
        coerce("WAT")


def test_resume_path_dsd_42():
    # AI_PAUSED → AI_ACTIVE is the explicit DSD §4.2 resume arc.
    assert_transition(S.AI_PAUSED, S.AI_ACTIVE)


def test_no_backward_arc_to_new():
    # NEW is an entry-only state.
    for state in S:
        if state is S.NEW:
            continue
        assert can_transition(state, S.NEW) is False
