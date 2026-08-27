"""Unit tests for the AIOrchestrator cascade router (Haiku->Sonnet)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.claude.client import ClaudeDecision, ClaudeUsage
from app.modules.ai.service import AIOrchestrator


def _decision(**overrides) -> ClaudeDecision:
    defaults = {
        "reply": "Hello!",
        "confidence": 0.95,
        "intent": "greeting",
        "suggested_tags": [],
        "requires_approval": False,
        "escalate": False,
    }
    return ClaudeDecision(**(defaults | overrides))


def _usage() -> ClaudeUsage:
    return ClaudeUsage(input_tokens=100, output_tokens=20)


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.propose_reply = AsyncMock(
        return_value=(_decision(), _usage(), 500)
    )
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def mock_session():
    """Minimal mock that satisfies the sync session expected by AIOrchestrator."""
    session = MagicMock()
    # Return None for DB gets - individual tests should set up proper mocks
    session.get.return_value = None
    session.execute.return_value = MagicMock()
    return session


class TestCascadeRouter:
    def test_haiku_faq_stays_on_haiku(self, mock_client, mock_session):
        """High-confidence FAQ -> Haiku only, no Sonnet call."""
        mock_client.propose_reply.return_value = (
            _decision(confidence=0.95, escalate=False, requires_approval=False),
            _usage(),
            500,
        )

        orch = AIOrchestrator(session=mock_session, client=mock_client)
        # _needs_escalation unit test
        assert not orch._needs_escalation(
            _decision(confidence=0.95, escalate=False, requires_approval=False)
        )

    def test_escalate_flag_triggers_sonnet(self, mock_client, mock_session):
        """escalate=true -> _needs_escalation returns True."""
        orch = AIOrchestrator(session=mock_session, client=mock_client)
        assert orch._needs_escalation(_decision(escalate=True))

    def test_requires_approval_triggers_sonnet(self, mock_client, mock_session):
        """requires_approval=true -> _needs_escalation returns True."""
        orch = AIOrchestrator(session=mock_session, client=mock_client)
        assert orch._needs_escalation(_decision(requires_approval=True))

    def test_gray_zone_confidence_triggers_sonnet(self, mock_client, mock_session):
        """confidence in [0.50, 0.85] -> _needs_escalation returns True."""
        orch = AIOrchestrator(session=mock_session, client=mock_client)
        assert orch._needs_escalation(_decision(confidence=0.65))

    def test_high_confidence_faq_no_escalation(self, mock_client, mock_session):
        """confidence=0.95, no flags -> _needs_escalation returns False."""
        orch = AIOrchestrator(session=mock_session, client=mock_client)
        assert not orch._needs_escalation(_decision(confidence=0.95))

    def test_low_confidence_below_floor_no_escalation(self, mock_client, mock_session):
        """confidence=0.30, no flags -> _needs_escalation returns False (below floor, not gray zone)."""
        orch = AIOrchestrator(session=mock_session, client=mock_client)
        assert not orch._needs_escalation(_decision(confidence=0.30))
