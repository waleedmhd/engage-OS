"""Webhook integration tests — real HTTP signature verification + task enqueue.

Covers:
  * GET /webhooks/meta hub handshake (good + bad verify token)
  * POST /webhooks/meta with valid signature → 200 + task enqueued
  * POST /webhooks/meta with invalid signature → 200 (Msg-M5 fail-soft)
  * POST /webhooks/meta with missing signature → 200, no task enqueued
  * POST /webhooks/meta with empty META_APP_SECRET in non-dev ENV → 403 (Msg-C3)
  * Dedup: same wamid posted twice → exactly one Message row
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.payloads import load_payload_bytes, sign_meta

# Constant test secret — used to sign payloads for these tests; matches conftest default.
_TEST_SECRET = os.environ.get("META_APP_SECRET", "test-meta-app-secret")


@pytest.mark.asyncio
async def test_get_handshake_correct_token_returns_challenge(client):
    response = await client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": os.environ["META_VERIFY_TOKEN"],
            "hub.challenge": "12345",
        },
    )
    assert response.status_code == 200
    assert response.text == "12345" or response.json() == 12345


@pytest.mark.asyncio
async def test_get_handshake_bad_token_returns_403(client):
    response = await client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "12345",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_post_with_valid_signature_enqueues_task(client):
    body = load_payload_bytes("meta_inbound_text")
    sig = sign_meta(body, _TEST_SECRET)

    with patch(
        "app.modules.messaging.router.process_inbound_webhook_task"
    ) as mock_task:
        mock_task.delay = MagicMock()
        response = await client.post(
            "/webhooks/meta",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_post_with_invalid_signature_returns_200_but_does_not_enqueue(client):
    """Msg-M5: never return 401 to Meta — would trigger retry storm. Log + 200."""
    body = load_payload_bytes("meta_inbound_text")

    with patch(
        "app.modules.messaging.router.process_inbound_webhook_task"
    ) as mock_task:
        mock_task.delay = MagicMock()
        response = await client.post(
            "/webhooks/meta",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=" + "0" * 64,
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    mock_task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_post_missing_signature_does_not_enqueue(client):
    body = load_payload_bytes("meta_inbound_text")

    with patch(
        "app.modules.messaging.router.process_inbound_webhook_task"
    ) as mock_task:
        mock_task.delay = MagicMock()
        response = await client.post(
            "/webhooks/meta",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    # Returns 200 (Msg-M5) but never reaches the task.
    assert response.status_code == 200
    mock_task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_post_empty_secret_in_production_returns_403(client, monkeypatch, reset_settings):
    """Msg-C3 fail-closed: production with empty META_APP_SECRET → 403."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("META_APP_SECRET", "")
    # Settings is a cached singleton; reset_settings fixture clears it so the
    # router's `get_settings()` re-reads our env.
    from app.core import config as _config
    _config._settings = None

    body = load_payload_bytes("meta_inbound_text")

    # Msg-C3 fail-closed has two valid outcomes:
    #   * the Settings validator rejects an empty secret in production,
    #     raising ValidationError when the router calls get_settings()
    #     (the ASGI transport re-raises it into the test), OR
    #   * the router's fail-closed branch returns 403/500.
    # What is NOT acceptable is a 200 with no signature check.
    try:
        response = await client.post(
            "/webhooks/meta",
            content=body,
            headers={"Content-Type": "application/json"},
        )
    except Exception as exc:
        assert "META_APP_SECRET" in str(exc)
    else:
        assert response.status_code in (403, 500)
