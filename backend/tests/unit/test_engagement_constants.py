"""Unit tests for engagement constants: outreach states, opt-out detection, delivery
failure classification — all pure logic, no database needed.
"""

from __future__ import annotations

import pytest

from app.modules.engagement.constants import (
    OUTREACH_TERMINAL_STATES,
    OPT_OUT_KEYWORDS,
    PERMANENT_FAILURE_CODES,
    OutreachState,
    detect_opt_out_keywords,
    is_permanent_failure,
    tag_for_failure_code,
)


class TestOutreachState:
    def test_terminal_states_non_overlapping(self):
        """Terminal states should be disjoint from intermediate states."""
        non_terminal = set(OutreachState) - OUTREACH_TERMINAL_STATES
        assert non_terminal, "should have non-terminal states"
        assert non_terminal & OUTREACH_TERMINAL_STATES == set()

    def test_state_values_are_unique(self):
        values = [s.value for s in OutreachState]
        assert len(values) == len(set(values)), "all state values must be unique"

    def test_terminal_states_included(self):
        for name in ("CONVERTED", "UNRESPONSIVE", "UNDELIVERABLE", "SUPPRESSED"):
            assert OutreachState[name] in OUTREACH_TERMINAL_STATES


class TestOptOutDetection:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("STOP", True),
            ("Unsubscribe", True),
            ("please stop messaging me", True),
            ("UNSTOP", True),
            ("stopall", True),
            ("How did you get my number", False),  # not a keyword match
            ("hello there", False),
            ("", False),
            (None, False),
            ("  STOP  ", True),
            ("don't contact me anymore", True),
            ("do not message me please", True),
            ("remove me from your list", True),
        ],
    )
    def test_detect_opt_out_keywords(self, text, expected):
        assert detect_opt_out_keywords(text) == expected

    def test_keywords_lowercase(self):
        """All keywords should be stored in lowercase for matching."""
        for kw in OPT_OUT_KEYWORDS:
            assert kw == kw.lower(), f"keyword '{kw}' must be lowercase"


class TestDeliveryFailure:
    @pytest.mark.parametrize(
        "code, expected",
        [
            (131026, True),
            (131047, True),
            (131049, True),
            (131051, True),
            (131052, True),
            (131053, True),
            (None, False),
            (500, False),
            (0, False),
            (131000, False),
        ],
    )
    def test_is_permanent_failure(self, code, expected):
        assert is_permanent_failure(code) == expected

    def test_tag_for_failure_code_not_on_whatsapp(self):
        assert tag_for_failure_code(131026) == "NOT_ON_WHATSAPP"
        assert tag_for_failure_code(131047) == "NOT_ON_WHATSAPP"
        assert tag_for_failure_code(131049) == "NOT_ON_WHATSAPP"
        assert tag_for_failure_code(131053) == "NOT_ON_WHATSAPP"

    def test_tag_for_failure_code_invalid_number(self):
        assert tag_for_failure_code(131052) == "INVALID_NUMBER"

    def test_tag_for_failure_code_undeliverable(self):
        assert tag_for_failure_code(131051) == "UNDELIVERABLE"

    def test_tag_for_failure_code_none(self):
        assert tag_for_failure_code(None) is None

    def test_tag_for_failure_code_unknown_permanent(self):
        """Any permanent code that doesn't match a specific bucket returns UNDELIVERABLE."""
        assert tag_for_failure_code(99999) == "UNDELIVERABLE"
