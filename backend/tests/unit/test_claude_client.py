"""Unit tests for ClaudeClient — Anthropic SDK wrapper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic import APITimeoutError, RateLimitError, APIStatusError

from app.core.exceptions import (
    AIProviderError,
    AIProviderInvalidResponseError,
    AIProviderTimeoutError,
)
from app.integrations.claude.client import ClaudeClient, ClaudeDecision, ClaudeUsage


# ----------------------------------------------------------------- helpers

def _make_tool_use_block(**input_kwargs):
    """Build a mock content block that behaves like an Anthropic ToolUseBlock.

    MagicMock(name="emit_decision") doesn't work because ``name`` is consumed
    by the Mock constructor as _mock_name, not stored as an attribute.
    """
    block = MagicMock(spec=["type", "name", "input"])
    block.type = "tool_use"
    block.name = "emit_decision"
    block.input = {
        "reply": "",
        "confidence": 0.95,
        "intent": "",
        "suggested_tags": [],
        "requires_approval": False,
        "escalate": False,
    }
    block.input.update(input_kwargs)
    return block


def _make_usage_mock(input_tokens=100, output_tokens=20,
                     cache_read=0, cache_create=0):
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = cache_read
    usage.cache_creation_input_tokens = cache_create
    return usage


def _set_up_client(messages_create_return=None, messages_create_side_effect=None):
    """Set up a ClaudeClient whose internal AsyncAnthropic is patched.

    Returns (client, mock_client) — the real client and the mock AsyncAnthropic
    underlying it.
    """
    mock_client = AsyncMock()
    if messages_create_side_effect is not None:
        mock_client.messages.create = AsyncMock(side_effect=messages_create_side_effect)
    else:
        mock_client.messages.create = AsyncMock(return_value=messages_create_return)

    with patch.object(ClaudeClient, "_get_client", return_value=mock_client):
        client = ClaudeClient()
        # Patch _get_client back in so subsequent calls (from aclose) also work.
        # _get_client sets self._client; since we mocked it, self._client stays
        # None.  Explicitly assign the mock so aclose() has something to close.
        client._client = mock_client

    return client, mock_client


# ----------------------------------------------------------------- success


class TestClaudeClientSuccess:
    @pytest.mark.asyncio
    async def test_propose_reply_parses_tool_use(self):
        """A well-formed tool_use block is parsed into ClaudeDecision."""
        mock_response = MagicMock()
        mock_response.content = [
            _make_tool_use_block(
                reply="Hello", confidence=0.95, intent="greeting",
            )
        ]
        mock_response.usage = _make_usage_mock(
            input_tokens=100, output_tokens=20, cache_create=50,
        )

        client, mock_client = _set_up_client(messages_create_return=mock_response)
        decision, usage, latency = await client.propose_reply(
            system_blocks=[{"type": "text", "text": "You are helpful."}],
            messages=[{"role": "user", "content": "Hi"}],
        )
        await client.aclose()

        assert decision.reply == "Hello"
        assert decision.confidence == 0.95
        assert decision.intent == "greeting"
        assert usage.input_tokens == 100
        assert usage.output_tokens == 20
        assert latency >= 0

    @pytest.mark.asyncio
    async def test_aclose_always_called(self):
        """aclose() is called even when propose_reply raises."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=APITimeoutError("timeout"))
        mock_client.close = AsyncMock()

        with patch.object(ClaudeClient, "_get_client", return_value=mock_client):
            client = ClaudeClient()
            client._client = mock_client

            with pytest.raises(AIProviderTimeoutError):
                await client.propose_reply(
                    system_blocks=[{"type": "text", "text": "You are helpful."}],
                    messages=[{"role": "user", "content": "Hi"}],
                )
            await client.aclose()

        mock_client.close.assert_awaited_once()


# ------------------------------------------------------------------ errors


class TestClaudeClientErrors:
    @pytest.mark.asyncio
    async def test_timeout_raises_ai_provider_timeout_error(self):
        """APITimeoutError → AIProviderTimeoutError (retryable)."""
        client, _ = _set_up_client(
            messages_create_side_effect=APITimeoutError("timeout"),
        )
        with pytest.raises(AIProviderTimeoutError) as exc_info:
            await client.propose_reply(
                system_blocks=[{"type": "text", "text": "You are helpful."}],
                messages=[{"role": "user", "content": "Hi"}],
            )
        await client.aclose()
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_rate_limit_raises_retryable_error(self):
        """429 → AIProviderError with retryable=True."""
        client, _ = _set_up_client(
            messages_create_side_effect=RateLimitError(
                "rate limited", response=MagicMock(), body=None,
            ),
        )
        with pytest.raises(AIProviderError) as exc_info:
            await client.propose_reply(
                system_blocks=[{"type": "text", "text": "You are helpful."}],
                messages=[{"role": "user", "content": "Hi"}],
            )
        await client.aclose()
        assert exc_info.value.retryable is True
        assert exc_info.value.code == "ai_provider_error"

    @pytest.mark.asyncio
    async def test_client_error_4xx_raises_non_retryable(self):
        """400 → AIProviderError with retryable=False."""
        client, _ = _set_up_client(
            messages_create_side_effect=APIStatusError(
                "bad request", response=MagicMock(status_code=400), body=None,
            ),
        )
        with pytest.raises(AIProviderError) as exc_info:
            await client.propose_reply(
                system_blocks=[{"type": "text", "text": "You are helpful."}],
                messages=[{"role": "user", "content": "Hi"}],
            )
        await client.aclose()
        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_missing_tool_use_raises_invalid_response(self):
        """Response with no tool_use block → AIProviderInvalidResponseError."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Sorry, I cannot help.")]
        mock_response.stop_reason = "end_turn"

        client, _ = _set_up_client(messages_create_return=mock_response)
        with pytest.raises(AIProviderInvalidResponseError):
            await client.propose_reply(
                system_blocks=[{"type": "text", "text": "You are helpful."}],
                messages=[{"role": "user", "content": "Hi"}],
            )
        await client.aclose()


# ------------------------------------------------------------------- usage


class TestClaudeClientUsage:
    @pytest.mark.asyncio
    async def test_usage_extracted_from_response(self):
        """Token counts are extracted from the Anthropic response."""
        mock_response = MagicMock()
        mock_response.content = [
            _make_tool_use_block(reply="Hi", confidence=0.9, intent="greeting"),
        ]
        mock_response.usage = _make_usage_mock(
            input_tokens=200, output_tokens=50,
            cache_read=30, cache_create=100,
        )

        client, _ = _set_up_client(messages_create_return=mock_response)
        _, usage, _ = await client.propose_reply(
            system_blocks=[{"type": "text", "text": "You are helpful."}],
            messages=[{"role": "user", "content": "Hi"}],
        )
        await client.aclose()

        assert usage.input_tokens == 200
        assert usage.output_tokens == 50
        assert usage.cache_read_input_tokens == 30
        assert usage.cache_creation_input_tokens == 100

    @pytest.mark.asyncio
    async def test_cache_read_tokens_reported(self):
        """cache_read_input_tokens is extracted correctly."""
        mock_response = MagicMock()
        mock_response.content = [
            _make_tool_use_block(reply="Hi", confidence=0.95, intent="greeting"),
        ]
        mock_response.usage = _make_usage_mock(
            input_tokens=100, output_tokens=20,
            cache_read=80,  # 80% cache hit!
        )

        client, _ = _set_up_client(messages_create_return=mock_response)
        _, usage, _ = await client.propose_reply(
            system_blocks=[{"type": "text", "text": "You are helpful."}],
            messages=[{"role": "user", "content": "Hi"}],
        )
        await client.aclose()

        assert usage.cache_read_input_tokens == 80
