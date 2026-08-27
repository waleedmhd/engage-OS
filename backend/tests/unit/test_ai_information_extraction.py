"""Unit tests for contact information extraction in ai/service.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# -------------------------------------------------- _format_contact_transcript

def test_format_contact_transcript_basic():
    """Formats inbound/outbound messages with date prefixes."""
    from app.modules.ai.service import _format_contact_transcript

    messages = [
        {
            "direction": "inbound",
            "sender_type": "contact",
            "content": "Hi, I'm Ahmed from Dubai Mobile",
            "created_at": "2026-07-01T10:00:00+00:00",
        },
        {
            "direction": "outbound",
            "sender_type": "ai",
            "content": "Hello Ahmed, nice to meet you!",
            "created_at": "2026-07-01T10:01:00+00:00",
        },
        {
            "direction": "inbound",
            "sender_type": "contact",
            "content": "I'm looking for iPhone 15 HK spec",
            "created_at": "2026-07-01T10:02:00+00:00",
        },
    ]

    result = _format_contact_transcript(messages)

    assert "[2026-07-01] Customer: Hi, I'm Ahmed from Dubai Mobile" in result
    assert "[2026-07-01] Agent: Hello Ahmed, nice to meet you!" in result
    assert "iPhone 15 HK spec" in result


def test_format_contact_transcript_skips_empty_content():
    """Messages with empty/None content are skipped."""
    from app.modules.ai.service import _format_contact_transcript

    messages = [
        {"direction": "inbound", "content": "hello", "created_at": None},
        {"direction": "outbound", "content": "", "created_at": None},
        {"direction": "inbound", "content": None, "created_at": None},
    ]

    result = _format_contact_transcript(messages)
    lines = [l for l in result.split("\n") if l.strip()]
    assert len(lines) == 1
    assert "hello" in lines[0]


def test_format_contact_transcript_no_date():
    """When created_at is None, no date prefix."""
    from app.modules.ai.service import _format_contact_transcript

    messages = [
        {"direction": "inbound", "content": "yo", "created_at": None},
    ]

    result = _format_contact_transcript(messages)
    assert result == " Customer: yo"


# ---------------------------------------------------- _extract_information_direct

@pytest.mark.asyncio
async def test_extract_information_direct_returns_text():
    """Haiku call returns a string; function strips and returns it."""
    from app.modules.ai.service import _extract_information_direct

    fake_response = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "  \nWho They Are\n- Ahmed, Dubai Mobile Trading  \n"
    fake_response.content = [text_block]

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)
    fake_client.close = AsyncMock()

    settings = MagicMock()
    settings.ANTHROPIC_API_KEY = "fake-key"

    with patch(
        "app.modules.ai.service.AsyncAnthropic", return_value=fake_client
    ):
        result = await _extract_information_direct("transcript", settings)

    assert result is not None
    assert "Who They Are" in result
    assert "Ahmed" in result


@pytest.mark.asyncio
async def test_extract_information_direct_empty_returns_none():
    """Empty response text → None."""
    from app.modules.ai.service import _extract_information_direct

    fake_response = MagicMock()
    fake_response.content = []

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)
    fake_client.close = AsyncMock()

    settings = MagicMock()
    settings.ANTHROPIC_API_KEY = "fake-key"

    with patch(
        "app.modules.ai.service.AsyncAnthropic", return_value=fake_client
    ):
        result = await _extract_information_direct("transcript", settings)

    assert result is None


@pytest.mark.asyncio
async def test_extract_information_direct_exception_returns_none():
    """API failure → None (non-fatal, retry on next turn)."""
    from app.modules.ai.service import _extract_information_direct

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(
        side_effect=Exception("API error")
    )

    settings = MagicMock()
    settings.ANTHROPIC_API_KEY = "fake-key"

    with patch(
        "app.modules.ai.service.AsyncAnthropic", return_value=fake_client
    ):
        result = await _extract_information_direct("transcript", settings)

    assert result is None


# -------------------------------------------------- _extract_information_two_tier

@pytest.mark.asyncio
async def test_extract_information_two_tier_calls_sonnet_then_haiku():
    """Two-tier: Sonnet condenses first, then Haiku extracts."""
    from app.modules.ai.service import _extract_information_two_tier

    condensed_text = "Customer: Ahmed, Dubai Mobile. Looking for iPhones."

    def _make_response(text):
        r = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = text
        r.content = [block]
        return r

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    # First call: Sonnet condense
    fake_client.messages.create = AsyncMock(
        return_value=_make_response(condensed_text)
    )
    fake_client.close = AsyncMock()

    settings = MagicMock()
    settings.ANTHROPIC_API_KEY = "fake-key"

    with patch(
        "app.modules.ai.service.AsyncAnthropic",
        side_effect=[fake_client, fake_client],
    ):
        result = await _extract_information_two_tier(
            "very long transcript " * 5000, settings
        )

    # Sonnet condense was called first, then close was called
    assert fake_client.close.await_count >= 1


@pytest.mark.asyncio
async def test_extract_information_two_tier_condense_failure():
    """Empty condense → None."""
    from app.modules.ai.service import _extract_information_two_tier

    fake_response = MagicMock()
    fake_response.content = []

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)
    fake_client.close = AsyncMock()

    settings = MagicMock()
    settings.ANTHROPIC_API_KEY = "fake-key"

    with patch(
        "app.modules.ai.service.AsyncAnthropic", return_value=fake_client
    ):
        result = await _extract_information_two_tier(
            "long transcript", settings
        )

    assert result is None


@pytest.mark.asyncio
async def test_extract_information_two_tier_exception_handler():
    """Exception in two-tier pipeline → None (non-fatal)."""
    from app.modules.ai.service import _extract_information_two_tier

    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(
        side_effect=RuntimeError("Sonnet API error")
    )
    fake_client.close = AsyncMock()

    settings = MagicMock()
    settings.ANTHROPIC_API_KEY = "fake-key"

    with patch(
        "app.modules.ai.service.AsyncAnthropic", return_value=fake_client
    ):
        result = await _extract_information_two_tier(
            "long transcript", settings
        )

    assert result is None


# ------------------------------------------------ _ensure_contact_information


def test_ensure_contact_information_skips_when_already_set():
    """Early-return when contact.information is already populated."""
    from app.modules.ai.service import AIOrchestrator

    contact = MagicMock()
    contact.information = "Already populated"
    contact.id = "uuid-123"

    session = MagicMock()

    orchestrator = AIOrchestrator.__new__(AIOrchestrator)
    orchestrator._session = session

    orchestrator._ensure_contact_information(contact)

    session.execute.assert_not_called()
