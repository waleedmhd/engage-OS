"""Router-level tests for the Meta webhook endpoint.

Covers:
- Msg-C3: signed/unsigned webhook handling, fail-closed when secret missing
- Msg-M5: invalid signature returns 200 + log (not 401) to avoid retry storm
- Msg-C4: outbound task dispatched AFTER session.commit
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest

from app.modules.messaging import router as router_module


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


@pytest.fixture
def patch_settings(monkeypatch):
    """Yield a setter that overrides settings used by the webhook router."""
    def _set(**kwargs) -> None:
        fake = MagicMock()
        for k, v in kwargs.items():
            setattr(fake, k, v)
        monkeypatch.setattr(router_module, "get_settings", lambda: fake)
    return _set


@pytest.fixture
def captured_delay(monkeypatch):
    """Capture process_inbound_webhook_task.delay calls without enqueueing."""
    calls: list[tuple] = []

    def _delay(*args, **kwargs):
        calls.append((args, kwargs))
        return MagicMock(id="task-id")

    monkeypatch.setattr(
        router_module.process_inbound_webhook_task, "delay", _delay
    )
    return calls


# ----------------------------------------------------------------- Msg-C3

@pytest.mark.asyncio
async def test_signed_webhook_accepted(client, patch_settings, captured_delay):
    """Msg-C3 happy path: properly signed webhook → 200 + task enqueued."""
    secret = "test-secret-32-chars-long-xxxxxxxx"
    patch_settings(META_APP_SECRET=secret, ENV="production",
                   META_VERIFY_TOKEN="t")

    payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    body = json.dumps(payload).encode()

    response = await client.post(
        "/webhooks/meta",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-hub-signature-256": _sign(body, secret),
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(captured_delay) == 1


@pytest.mark.asyncio
async def test_unsigned_webhook_returns_200_but_does_not_dispatch(
    client, patch_settings, captured_delay
):
    """Msg-C3 + Msg-M5: bad signature returns 200 (no retry storm) but task
    is NOT enqueued. Only genuine misconfiguration (missing secret in prod)
    returns 403."""
    secret = "test-secret-32-chars-long-xxxxxxxx"
    patch_settings(META_APP_SECRET=secret, ENV="production",
                   META_VERIFY_TOKEN="t")

    payload = {"entry": []}
    body = json.dumps(payload).encode()

    response = await client.post(
        "/webhooks/meta",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-hub-signature-256": "sha256=deadbeef" * 8,
        },
    )

    # Msg-M5: returns 200 to stop Meta retries.
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    # Critical: bad signature must NOT enqueue work.
    assert len(captured_delay) == 0


@pytest.mark.asyncio
async def test_webhook_returns_403_when_secret_missing_in_production(
    client, patch_settings, captured_delay
):
    """Msg-C3: empty secret in production → 403 (fail-closed)."""
    patch_settings(META_APP_SECRET="", ENV="production",
                   META_VERIFY_TOKEN="t")

    response = await client.post(
        "/webhooks/meta",
        content=b'{"entry": []}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 403
    assert len(captured_delay) == 0


# ----------------------------------------------------------------- Msg-C4

def test_outbound_send_message_does_not_dispatch_task(monkeypatch):
    """Msg-C4: MessagingService.send_message must NOT dispatch the Celery
    task — that responsibility moved to the router (after session.commit).

    Static check: confirm the service module never imports
    send_outbound_message_task.
    """
    # Parse the module AST and walk for any actual function/method call that
    # ends in `.delay(...)`. This skips strings/docstrings entirely.
    import ast
    import inspect

    from app.modules.messaging import service as svc_module

    tree = ast.parse(inspect.getsource(svc_module))
    delay_calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "delay":
                delay_calls.append(node)

    assert not delay_calls, (
        "Msg-C4 regression: messaging/service.py contains a .delay() call. "
        "The router is responsible for dispatching after session.commit()."
    )


def test_outbound_router_dispatches_after_commit(monkeypatch):
    """Msg-C4: in router.send_message the task.delay call MUST appear AFTER
    session.commit. This is a textual ordering check on the router source —
    if someone reorders the lines, the test fails.
    """
    import inspect

    from app.modules.messaging import router as router_module

    src = inspect.getsource(router_module.send_message)
    commit_idx = src.find("session.commit()")
    delay_idx = src.find("send_outbound_message_task.delay")

    assert commit_idx > 0, "session.commit() not found in router.send_message"
    assert delay_idx > 0, "send_outbound_message_task.delay not found in router.send_message"
    assert commit_idx < delay_idx, (
        "Msg-C4 regression: send_outbound_message_task.delay() must be called "
        "AFTER session.commit() — otherwise the worker may read the row before "
        "it is durable."
    )


@pytest.mark.asyncio
async def test_webhook_skips_signature_in_development(
    client, patch_settings, captured_delay
):
    """Development convenience: empty secret + ENV=development → 200, dispatched.

    This is intentional per Msg-C3 fix to ease local testing without a
    real Meta app. The fail-closed behavior only applies to non-development
    environments.
    """
    patch_settings(META_APP_SECRET="", ENV="development",
                   META_VERIFY_TOKEN="t")

    response = await client.post(
        "/webhooks/meta",
        content=b'{"entry": []}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert len(captured_delay) == 1
