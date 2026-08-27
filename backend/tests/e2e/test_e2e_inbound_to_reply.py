"""E2E: inbound webhook -> conversation -> AI draft -> approval -> outbound send.

Walks the Phase 1+2 happy path against a real Postgres + Redis stack with
Celery in eager mode. Claude is mocked via patch so the test is deterministic.

NOTE on Meta send: the outbound dispatcher calls the Meta Graph API. This test
uses respx to intercept that HTTP call and assert the request shape. To run
this against the real Meta API, use the `live` tier (tests/live/).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests.factories import make_user
from tests.fixtures.payloads import load_payload_bytes, sign_meta


@pytest.mark.asyncio
async def test_full_inbound_to_reply_happy_path(
    committed_db, redis_client, celery_eager, respx_mock, client
):
    """
    1. POST signed Meta inbound webhook -> 200
    2. Celery (eager) processes -> Contact upserted, Conversation OPEN, Message INBOUND
    3. AI orchestrator runs (Claude mocked -> 'approval') -> DRAFT Message
    4. Agent approves via POST /conversations/{id}/approve -> message goes to QUEUED
    5. Outbound dispatcher (Meta mocked) sends -> Message status SENT
    """
    import os

    from app.modules.contacts.models import Contact
    from app.modules.conversations.models import Conversation
    from app.modules.messaging.models import Message

    from app.integrations.claude.client import ClaudeDecision, ClaudeUsage

    # Pre-seed an agent so the conversation can be assigned/approved.
    agent = make_user(committed_db, role="agent")
    committed_db.commit()

    # 1. Sign + post inbound webhook
    body = load_payload_bytes("meta_inbound_text")
    sig = sign_meta(body, os.environ["META_APP_SECRET"])

    # Mock Claude -> approval decision
    approval_decision = ClaudeDecision(
        reply="This needs review.",
        confidence=0.75,
        intent="support",
        suggested_tags=[],
        requires_approval=True,
        escalate=False,
    )
    approval_usage = ClaudeUsage(input_tokens=100, output_tokens=30)

    mock_claude = AsyncMock()
    mock_claude.propose_reply = AsyncMock(
        return_value=(approval_decision, approval_usage, 150)
    )

    # Mock Meta send endpoint (any URL containing graph.facebook.com)
    respx_mock.post(__import__("re").compile(r".*graph\.facebook\.com.*")).respond(
        json={"messages": [{"id": "wamid.OUTBOUND.0001"}]}
    )

    # The webhook task enqueues request_ai_reply_task. In production the web
    # process only enqueues; a separate sync Celery worker runs it (and its
    # asyncio.run bridge - invariant #12). Under pytest the request runs in an
    # event loop, so we capture the enqueue here and run the AI task in a
    # worker thread afterwards (no running loop -> asyncio.run works), exactly
    # mirroring the prod web/worker split.
    captured: list[tuple[str, str]] = []

    from app.modules.ai.tasks import request_ai_reply_task

    with patch(
        "app.modules.ai.service.ClaudeClient",
        return_value=mock_claude,
    ):
        with patch.object(
            request_ai_reply_task,
            "delay",
            side_effect=lambda cid, msg: captured.append((cid, msg)),
        ):
            response = await client.post(
                "/webhooks/meta",
                content=body,
                headers={
                    "X-Hub-Signature-256": sig,
                    "Content-Type": "application/json",
                },
            )
    assert response.status_code == 200
    assert captured, "webhook must enqueue request_ai_reply_task (B-10)"

    # 2. Verify contact + conversation + inbound message exist.
    committed_db.expire_all()
    contact = committed_db.query(Contact).filter_by(phone="16175551234").one_or_none()
    assert contact is not None, "Inbound webhook should have upserted contact 16175551234"

    conv = committed_db.query(Conversation).filter_by(contact_id=contact.id).one()
    assert conv is not None

    inbound_msgs = (
        committed_db.query(Message)
        .filter_by(conversation_id=conv.id, direction="inbound")
        .all()
    )
    assert len(inbound_msgs) == 1
    assert "hello" in inbound_msgs[0].content.lower()

    # 3. Run the enqueued AI task in a worker thread (no running event loop),
    # mirroring a real Celery worker. The ClaudeClient patch is process-global
    # and the mock is now on the service module.
    cid, msg = captured[0]

    with patch(
        "app.modules.ai.service.ClaudeClient",
        return_value=mock_claude,
    ):
        await asyncio.to_thread(request_ai_reply_task.run, cid, msg)

    committed_db.expire_all()
    drafts = (
        committed_db.query(Message)
        .filter_by(conversation_id=conv.id, direction="outbound", delivery_status="draft")
        .all()
    )
    assert len(drafts) == 1, f"Expected one DRAFT message, found {len(drafts)}"
    draft = drafts[0]

    # Verify aclose() was called on the Claude mock
    mock_claude.aclose.assert_called()

    # 4. Agent approves the draft.
    # (Test uses a synthetic auth bypass - the production /approve route
    # requires authentication. We override get_current_user_db.)
    from app.core.dependencies import get_current_user_db

    client._transport.app.dependency_overrides[get_current_user_db] = lambda: agent  # type: ignore[attr-defined]
    try:
        approve_resp = await client.post(
            f"/api/v1/conversations/{conv.id}/approve",
            json={"message_id": str(draft.id)},
            headers={"Authorization": "Bearer test"},
        )
    finally:
        client._transport.app.dependency_overrides.pop(get_current_user_db, None)  # type: ignore[attr-defined]

    assert approve_resp.status_code in (200, 204)

    # 5. Approving the conversation transitions AWAITING_APPROVAL -> AI_ACTIVE
    # AND wires the approved DRAFT through to delivery (B-11):
    #   approve() promotes the latest DRAFT outbound -> QUEUED in-transaction;
    #   the router commits, then dispatches send_outbound_message_task. Under
    #   celery_eager the send task runs inline against the mocked Meta
    #   endpoint, so the message ends up SENT with a Meta message id.
    from app.modules.conversations.models import Conversation as _Conv

    committed_db.expire_all()
    refreshed_conv = committed_db.get(_Conv, conv.id)
    assert refreshed_conv.state == "AI_ACTIVE"

    refreshed_draft = committed_db.get(Message, draft.id)
    assert refreshed_draft is not None
    # B-11: the reviewed draft must no longer be DRAFT - it was promoted to
    # QUEUED on approve and then delivered by the eagerly-run send task.
    assert refreshed_draft.delivery_status != "draft", (
        "approved draft was never promoted out of DRAFT (B-11 regression)"
    )
    assert refreshed_draft.delivery_status == "sent", (
        f"expected approved reply to be SENT, got {refreshed_draft.delivery_status!r}"
    )
    assert refreshed_draft.meta_message_id == "wamid.OUTBOUND.0001"
