"""Unit tests for AIEventReadService — repo is AsyncMocked.

Covers offset arithmetic and the (rows, total) contract that backs
GET /ai/events/{conversation_id} (admin observability surface, DSD §10).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.schemas import AIEventResponse
from app.modules.ai.service import AIEventReadService


def _make_service() -> AIEventReadService:
    svc = AIEventReadService(AsyncMock())
    svc._repo = AsyncMock()  # type: ignore[assignment]
    return svc


def _event(**over):
    base = dict(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        intent="faq",
        confidence=Decimal("0.912"),
        latency_ms=137,
        cost_estimate=Decimal("0.0000"),
        error=None,
        created_at=datetime.now(UTC),
        request={"incoming_message": "hi"},
        response={"reply": "hello"},
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_list_by_conversation_computes_offset_from_page():
    svc = _make_service()
    svc._repo.list_by_conversation.return_value = ([_event(), _event()], 42)  # type: ignore[attr-defined]
    cid = uuid.uuid4()

    rows, total = await svc.list_by_conversation(cid, page=3, page_size=20)

    assert total == 42
    assert len(rows) == 2
    # page=3, page_size=20 => offset=40
    svc._repo.list_by_conversation.assert_awaited_once_with(  # type: ignore[attr-defined]
        cid, limit=20, offset=40
    )


@pytest.mark.asyncio
async def test_list_by_conversation_first_page_offset_is_zero():
    svc = _make_service()
    svc._repo.list_by_conversation.return_value = ([], 0)  # type: ignore[attr-defined]
    cid = uuid.uuid4()

    await svc.list_by_conversation(cid, page=1, page_size=50)

    svc._repo.list_by_conversation.assert_awaited_once_with(  # type: ignore[attr-defined]
        cid, limit=50, offset=0
    )


def test_ai_event_response_coerces_decimal_to_float():
    """Numeric columns surface as Decimal; ensure JSON output is numeric."""
    row = _event(confidence=Decimal("0.875"), cost_estimate=Decimal("0.0042"))

    resp = AIEventResponse.model_validate(row)

    assert isinstance(resp.confidence, float)
    assert resp.confidence == 0.875
    assert isinstance(resp.cost_estimate, float)
    assert resp.cost_estimate == 0.0042


def test_ai_event_response_handles_null_optional_fields():
    row = _event(
        intent=None,
        confidence=None,
        latency_ms=None,
        cost_estimate=None,
        error="ai_provider_timeout:upstream",
    )

    resp = AIEventResponse.model_validate(row)

    assert resp.intent is None
    assert resp.confidence is None
    assert resp.latency_ms is None
    assert resp.cost_estimate is None
    assert resp.error == "ai_provider_timeout:upstream"
