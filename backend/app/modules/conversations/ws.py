"""Live inbox WebSocket handler (P2.1).

Auth: the HTTP Bearer/cookie dependency does NOT run for WebSockets,
so the JWT is read from the ``?token=`` query param and verified with
the same ``decode_access_token`` helper used by the REST API. Invalid
/ missing token → close 4401 (app-level "unauthorized") BEFORE accept.

Fan-out: domain events published to the Redis ``events:inbox`` channel
by worker/API processes (see app.core.events._publish_to_pubsub) are
relayed verbatim as JSON text frames.

Redis-py 5.x async pub/sub: ``pubsub.listen()`` is a self-contained
async generator that calls ``parse_response(block=True)`` internally.
It does NOT need a background ``pubsub.run()`` task — that method is
only for the callback-based pattern where handlers are passed to
``subscribe(channel=handler)``.  Without handlers, ``run()`` raises
``PubSubError`` because each channel has ``None`` registered.
"""

from __future__ import annotations

import asyncio

from fastapi import WebSocket, WebSocketDisconnect

from app.core.events import INBOX_PUBSUB_CHANNEL
from app.core.redis import get_async_redis
from app.core.security import decode_access_token


async def ws_inbox(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401, reason="missing_token")
        return
    try:
        decode_access_token(token)
    except Exception:
        await websocket.close(code=4401, reason="invalid_token")
        return

    await websocket.accept()
    redis = get_async_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(INBOX_PUBSUB_CHANNEL)

    async def _relay() -> None:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])

    relay_task = asyncio.create_task(_relay())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        relay_task.cancel()
        try:
            await relay_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await pubsub.unsubscribe(INBOX_PUBSUB_CHANNEL)
            await pubsub.aclose()
        except Exception:
            pass
