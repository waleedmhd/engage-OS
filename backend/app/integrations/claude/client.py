"""Claude / Anthropic SDK async client wrapper (DSD §4.3 replacement).

Replaces ``Base44SuperagentClient`` with a direct Anthropic SDK integration:
  - Tenacity retries for transient API errors (429, 5xx, connection).
  - Prompt caching on the stable system-prompt prefix.
  - Tool-choice enforcement (emit_decision tool) for structured output.
  - Usage metadata (input/output/cache tokens) for accurate cost tracking.

The public contract mirrors the former Base44 client so the orchestrator
refactor is mechanical:
  ``propose_reply(...) -> tuple[ClaudeDecision, ClaudeUsage, int]``
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from anthropic import (
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    InternalServerError,
    RateLimitError,
)
from anthropic.types import Message as AnthropicMessage
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AIProviderError,
    AIProviderInvalidResponseError,
    AIProviderTimeoutError,
)

logger = structlog.get_logger(__name__)

# Retryable Anthropic status codes
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


# ------------------------------------------------------------------ schemas


class ClaudeDecision(BaseModel):
    """Structured decision emitted by Claude via the emit_decision tool."""

    reply: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    intent: str = ""
    suggested_tags: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    escalate: bool = False
    detected_opt_out: bool = False
    send_contact_card: bool = False
    send_business_card_image: bool = False


class ClaudeUsage(BaseModel):
    """Token usage as returned by Anthropic's API."""

    input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    output_tokens: int = 0


# ------------------------------------------------------- tool definition


def _build_decision_tool(tag_taxonomy: tuple[str, ...]) -> dict[str, Any]:
    """Build the emit_decision tool definition, constraining suggested_tags
    to the fixed tag taxonomy to prevent hallucinated tags at the source."""
    return {
        "name": "emit_decision",
        "description": (
            "Return the assistant's decision for this WhatsApp conversation turn."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reply": {
                    "type": "string",
                    "description": "Customer-facing reply text. Empty string if no reply.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Confidence score for the primary action.",
                },
                "intent": {
                    "type": "string",
                    "description": "Detected user intent category.",
                },
                "suggested_tags": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(tag_taxonomy)},
                    "description": "Tag names from the supported taxonomy.",
                },
                "requires_approval": {
                    "type": "boolean",
                    "description": "True if the reply needs human review before sending.",
                },
                "escalate": {
                    "type": "boolean",
                    "description": "True if the conversation requires immediate human takeover.",
                },
                "detected_opt_out": {
                    "type": "boolean",
                    "description": "True if the contact's message signals they want to stop being contacted — explicit keywords (STOP, unsubscribe, any language) or implied signals (annoyance, disinterest, 'how did you get my number'). Must be checked FIRST before any other decision. Default false.",
                },
                "send_contact_card": {
                    "type": "boolean",
                    "description": "Set to true ONLY when the conversation context is right for sharing your contact card: (1) the contact explicitly asked for your number/card, (2) you have both agreed to exchange broadcast list info, or (3) the contact asked about stock and you haven't mentioned the broadcast list yet. Your reply text MUST explain WHY you are sending the card (e.g. 'here is my number for the broadcast list'). NEVER set this to true alongside an unrelated reply or in the first few messages of a conversation.",
                },
                "send_business_card_image": {
                    "type": "boolean",
                    "description": "Set to true when someone asks for your business card and you want to send the business card image file. The system will attach the actual image. Your reply text should still be conversational (e.g. 'sure here is my card').",
                },
            },
            "required": [
                "reply",
                "confidence",
                "intent",
                "suggested_tags",
                "requires_approval",
                "escalate",
                "detected_opt_out",
            ],
        },
    }


TOOL_CHOICE: dict[str, Any] = {"type": "tool", "name": "emit_decision"}


# ------------------------------------------------------------------ client


class ClaudeClient:
    """Async Anthropic SDK wrapper with tool-choice enforcement.

    Mirrors the ``Base44SuperagentClient`` contract so the orchestrator
    refactor is mechanical. Callers use ``propose_reply()`` which returns
    ``(ClaudeDecision, ClaudeUsage, latency_ms)``.

    Retries transient errors via tenacity (3 attempts, exponential backoff
    0.5 s → 8 s). Terminal failures are converted to ``AIProviderError``
    with the ``retryable`` flag set so the Celery task retry policy can act.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        tag_taxonomy: tuple[str, ...] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client: AsyncAnthropic | None = None
        self._decision_tool = _build_decision_tool(
            tag_taxonomy or ()
        )

    # --------------------------------------------------------------- public

    async def propose_reply(
        self,
        *,
        system_blocks: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> tuple[ClaudeDecision, ClaudeUsage, int]:
        """Call Claude with the given prompt and parse the tool output.

        Returns ``(decision, usage, latency_ms)``. Raises
        ``AIProviderError`` / ``AIProviderTimeoutError`` on failure.
        """
        client = self._get_client()
        model_id = model or self._settings.AI_MODEL_BULK

        started = time.monotonic()

        try:
            response: AnthropicMessage = await _make_request(
                client=client,
                model=model_id,
                system_blocks=system_blocks,
                tools=[self._decision_tool],
                tool_choice=TOOL_CHOICE,
                messages=messages,
                max_tokens=self._settings.AI_MAX_OUTPUT_TOKENS,
            )
        except APITimeoutError as exc:
            raise AIProviderTimeoutError(
                "anthropic_request_timeout",
                details={
                    "timeout_seconds": self._settings.AI_REQUEST_TIMEOUT_SECONDS
                },
            ) from exc
        except RateLimitError as exc:
            raise AIProviderError(
                "anthropic_rate_limited",
                details={"status": exc.status_code, "message": str(exc)},
                retryable=True,
            ) from exc
        except APIStatusError as exc:
            raise AIProviderError(
                "anthropic_api_error",
                details={"status": exc.status_code, "message": str(exc)[:500]},
                retryable=exc.status_code in _RETRYABLE_STATUS,
            ) from exc
        except (ConnectionError, APIError) as exc:
            raise AIProviderError(
                "anthropic_transport_error",
                details={"error": str(exc)},
                retryable=True,
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        decision = _parse_decision(response)
        usage = _extract_usage(response)

        self._log_usage(model_id, response)

        return decision, usage, latency_ms

    async def aclose(self) -> None:
        """Close the underlying Anthropic client session."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # -------------------------------------------------------------- private

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            if not self._settings.ANTHROPIC_API_KEY:
                raise AIProviderError("anthropic_api_key_not_configured")
            self._client = AsyncAnthropic(
                api_key=self._settings.ANTHROPIC_API_KEY,
                timeout=self._settings.AI_REQUEST_TIMEOUT_SECONDS,
            )
        return self._client

    @staticmethod
    def _log_usage(model: str, resp: AnthropicMessage) -> None:
        u = resp.usage
        logger.info(
            "claude_usage",
            model=model,
            input_tokens=u.input_tokens if u else 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) if u else 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) if u else 0,
            output_tokens=u.output_tokens if u else 0,
        )


# ------------------------------------------------------------------ helpers


@retry(
    retry=retry_if_exception_type(
        (APITimeoutError, RateLimitError, InternalServerError, ConnectionError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
    reraise=True,
)
async def _make_request(
    *,
    client: AsyncAnthropic,
    model: str,
    system_blocks: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any],
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> AnthropicMessage:
    """Single Claude API call with tenacity retry wrapper."""
    return await client.messages.create(  # type: ignore[call-overload]
        model=model,
        max_tokens=max_tokens,
        system=system_blocks,
        tools=tools,
        tool_choice=tool_choice,
        messages=messages,
    )


def _parse_decision(response: AnthropicMessage) -> ClaudeDecision:
    """Extract and validate ClaudeDecision from Anthropic tool-use response."""
    for block in response.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "emit_decision"
            and hasattr(block, "input")
        ):
            tool_input: object = getattr(block, "input")
            try:
                return ClaudeDecision.model_validate(dict(tool_input))  # type: ignore[call-overload]
            except Exception as exc:
                raise AIProviderInvalidResponseError(
                    details={
                        "error": str(exc),
                        "tool_name": getattr(block, "name", ""),
                        "raw_input": str(tool_input)[:500],
                    }
                ) from exc

    raise AIProviderInvalidResponseError(
        details={
            "stop_reason": str(response.stop_reason),
            "content_blocks": [getattr(c, "type", "?") for c in response.content],
        }
    )


def _extract_usage(response: AnthropicMessage) -> ClaudeUsage:
    """Pull token counts from the Anthropic usage block."""
    usage = response.usage
    if usage is None:
        return ClaudeUsage()
    return ClaudeUsage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )
