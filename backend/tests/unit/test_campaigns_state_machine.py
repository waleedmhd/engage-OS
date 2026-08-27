"""Pure tests for the campaign state-machine table.

These run without a DB — they exercise the ALLOWED_TRANSITIONS map directly.
The mapping is the single source of truth used by CampaignService._assert_transition;
keeping the table tested separately catches accidental edits during refactors.
"""

from __future__ import annotations

import pytest

from app.modules.campaigns.constants import ALLOWED_TRANSITIONS, CampaignStatus


@pytest.mark.parametrize(
    "src,dst",
    [
        (CampaignStatus.DRAFT, CampaignStatus.VALIDATING),
        (CampaignStatus.VALIDATING, CampaignStatus.SCHEDULED),
        (CampaignStatus.VALIDATING, CampaignStatus.FAILED),
        (CampaignStatus.SCHEDULED, CampaignStatus.QUEUED),
        (CampaignStatus.SCHEDULED, CampaignStatus.CANCELLED),
        (CampaignStatus.QUEUED, CampaignStatus.DISPATCHING),
        (CampaignStatus.DISPATCHING, CampaignStatus.COMPLETED),
        (CampaignStatus.DISPATCHING, CampaignStatus.FAILED),
        (CampaignStatus.DISPATCHING, CampaignStatus.SCHEDULED),  # recurring re-arm
        (CampaignStatus.DISPATCHING, CampaignStatus.CANCELLED),
    ],
)
def test_allowed_transitions(src: CampaignStatus, dst: CampaignStatus) -> None:
    assert dst in ALLOWED_TRANSITIONS[src], (
        f"expected {src.value} → {dst.value} to be allowed"
    )


@pytest.mark.parametrize(
    "src,dst",
    [
        (CampaignStatus.DRAFT, CampaignStatus.QUEUED),  # must validate first
        (CampaignStatus.DRAFT, CampaignStatus.COMPLETED),
        (CampaignStatus.SCHEDULED, CampaignStatus.COMPLETED),
        (CampaignStatus.COMPLETED, CampaignStatus.SCHEDULED),
        (CampaignStatus.FAILED, CampaignStatus.QUEUED),
        (CampaignStatus.CANCELLED, CampaignStatus.SCHEDULED),
    ],
)
def test_disallowed_transitions(src: CampaignStatus, dst: CampaignStatus) -> None:
    assert dst not in ALLOWED_TRANSITIONS[src], (
        f"{src.value} → {dst.value} should be illegal"
    )


def test_terminal_states_have_no_outgoing_edges() -> None:
    for terminal in (
        CampaignStatus.COMPLETED,
        CampaignStatus.FAILED,
        CampaignStatus.CANCELLED,
    ):
        assert ALLOWED_TRANSITIONS[terminal] == set(), (
            f"terminal state {terminal.value} should have no transitions"
        )


def test_every_status_appears_as_a_key() -> None:
    """Defensive: forgetting a key would cause _assert_transition to KeyError."""
    for status in CampaignStatus:
        assert status in ALLOWED_TRANSITIONS, (
            f"status {status.value} missing from ALLOWED_TRANSITIONS"
        )
