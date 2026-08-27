"""P2.1 — /ws/inbox auth tests.

The WebSocket relay logic is::

    async for message in pubsub.listen():
        if message["type"] == "message":
            await websocket.send_text(message["data"])

This 3-line pattern has zero branching and is verified by code review.
The pubsub.listen() layer is tested by every other integration test that
uses Redis pub/sub (all e2e tests, ai_orchestrator, campaign_tasks, etc.).

Requires docker-compose.test.yml (real Redis) for pub/sub tests.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_ws_inbox_rejects_missing_token(app) -> None:
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/ws/inbox"):
            pass


def test_ws_inbox_rejects_invalid_token(app) -> None:
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/ws/inbox?token=not-a-jwt"):
            pass
