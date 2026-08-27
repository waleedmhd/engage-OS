"""Live Meta WhatsApp Cloud API contract tests.

WARNING — opt-in only. These tests:
  * Hit Meta Graph endpoints with real credentials from .env.
  * Send a real template message to META_TEST_RECIPIENT.
  * Cost a small per-conversation charge.

Run with:
    $env:RUN_LIVE_TESTS = "1"
    $env:META_TEST_RECIPIENT = "+1XXXXXXXXXX"   # your verified test number
    pytest -m live tests/live/test_live_meta_smoke.py
"""
from __future__ import annotations

import os

import pytest


def test_meta_phone_number_id_is_valid():
    """GET /{phone_number_id} should return the WABA phone metadata. This
    proves META_ACCESS_TOKEN + META_PHONE_NUMBER_ID are coherent."""
    import httpx

    phone_id = os.environ["META_PHONE_NUMBER_ID"]
    token = os.environ["META_ACCESS_TOKEN"]
    version = os.environ.get("META_API_VERSION", "v25.0")

    resp = httpx.get(
        f"https://graph.facebook.com/{version}/{phone_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "id" in body
    assert body["id"] == phone_id


def test_meta_send_template_to_test_recipient():
    """Send a `hello_world` template (Meta's pre-approved default) to the
    configured test recipient. Verifies the outbound path end-to-end."""
    import httpx

    recipient = os.environ.get("META_TEST_RECIPIENT")
    if not recipient:
        pytest.skip("Set META_TEST_RECIPIENT to a verified WhatsApp number to run this test")

    phone_id = os.environ["META_PHONE_NUMBER_ID"]
    token = os.environ["META_ACCESS_TOKEN"]
    version = os.environ.get("META_API_VERSION", "v25.0")

    resp = httpx.post(
        f"https://graph.facebook.com/{version}/{phone_id}/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient.lstrip("+"),
            "type": "template",
            "template": {"name": "hello_world", "language": {"code": "en_US"}},
        },
        timeout=15.0,
    )
    # Meta returns 200 with a `messages` array containing a wamid on success.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "messages" in body and len(body["messages"]) == 1
    assert body["messages"][0]["id"].startswith("wamid.")
