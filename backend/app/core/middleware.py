"""HTTP middleware: request ID and structured access logging.

All middleware is written as pure ASGI middleware (not Starlette
BaseHTTPMiddleware) so WebSocket upgrade requests pass through unmodified.
BaseHTTPMiddleware internally consumes the request body via StreamingResponse,
which breaks the WebSocket handshake and causes Uvicorn to reject the
connection with HTTP 403.

Modularity note: ReadOnlyModeMiddleware lazily imports from
``app.modules.settings`` (constants and repository) to read the read-only-mode
flag from the database. This is an acknowledged inversion — the middleware sits
at the composition-root level and may reach into domain modules for
configuration that must be queryable on every request. The import is lazy
(inside _fetch_db_read_only) and the value is TTL-cached for 10 seconds to
avoid per-request DB round-trips.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Awaitable, Callable

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# DSD §11 — "Database Failure → read-only emergency mode". Mutating verbs
# are blocked when READ_ONLY_MODE is engaged.
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# The Meta webhook MUST keep returning 200 even in read-only mode, otherwise
# Meta enters an aggressive retry storm. It only enqueues a Celery task; the
# DB write happens in the worker, which already retries on failure (acks_late).
# So we exempt the webhook path here and let the task layer absorb DB outage.
#
# Piece 2 also exempts /settings/operational: once an admin engages the
# DB-backed read-only flag via that endpoint, they must still be able to
# disable it via the same endpoint without an env-var redeploy. The endpoint
# is already admin-only, so the exemption does not widen the attack surface.
_READ_ONLY_EXEMPT_PREFIXES = (
    "/webhooks/",
    "/api/v1/settings/operational",
)


# Piece 2: the read-only flag may also be set at runtime via
# PUT /settings/operational ({"read_only_mode": {"enabled": true}}). To
# avoid a DB hit on every mutating request we cache it in-process for a
# short TTL; a flip therefore takes effect within ~10s without a redeploy.
_RO_CACHE: dict[str, float | bool] = {"value": False, "fetched_at": 0.0}
_RO_CACHE_TTL_SECONDS = 10.0


async def _fetch_db_read_only() -> bool:
    """Read ops.read_only_mode from the DB. Isolated for test seams."""
    from app.db.session import async_session_factory
    from app.modules.settings.constants import SETTING_OPS_READ_ONLY_MODE
    from app.modules.settings.repository import SettingsRepository

    async with async_session_factory() as session:
        row = await SettingsRepository(session).get(
            SETTING_OPS_READ_ONLY_MODE, scope="global"
        )
    if row is None or not isinstance(row.value, dict):
        return False
    return bool(row.value.get("enabled", False))


async def _db_read_only_enabled() -> bool:
    """TTL-cached. Fail-open: any error -> False (env stays authoritative)."""
    now = time.monotonic()
    if now - float(_RO_CACHE["fetched_at"]) < _RO_CACHE_TTL_SECONDS:
        return bool(_RO_CACHE["value"])
    try:
        value = await asyncio.wait_for(_fetch_db_read_only(), timeout=5.0)
    except Exception:
        logger.warning("read_only_db_flag_fetch_failed", exc_info=True)
        value = False
    _RO_CACHE["value"] = value
    _RO_CACHE["fetched_at"] = now
    return value


class ReadOnlyModeMiddleware:
    """Return 503 for mutating requests while the app is in read-only mode.

    GET/HEAD/OPTIONS always pass through so the dashboard stays usable for
    incident triage. The flag is read fresh per request so flipping
    READ_ONLY_MODE takes effect without a redeploy.

    Written as pure ASGI middleware — not BaseHTTPMiddleware — so WebSocket
    upgrade requests (scope["type"] == "websocket") pass through unmodified.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        is_mutating = request.method in _MUTATING_METHODS
        is_exempt = any(
            request.url.path.startswith(p)
            for p in _READ_ONLY_EXEMPT_PREFIXES
        )
        read_only = is_mutating and not is_exempt and (
            get_settings().READ_ONLY_MODE or await _db_read_only_enabled()
        )
        if read_only:
            logger.warning(
                "read_only_mode_rejected_write",
                method=request.method,
                path=request.url.path,
            )
            response = JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "read_only_mode",
                        "message": (
                            "Service is in read-only emergency mode; "
                            "write operations are temporarily unavailable."
                        ),
                        "details": {},
                    }
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class RequestIDMiddleware:
    """Ensure every HTTP request carries an x-request-id header.

    Pure ASGI middleware — WebSocket connections pass through unmodified.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = structlog.contextvars.bind_contextvars(request_id=request_id)

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-request-id", request_id.encode("latin-1"))
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            del token


class AccessLogMiddleware:
    """Log every HTTP request with method, path, status, and duration.

    Pure ASGI middleware — WebSocket connections pass through unmodified.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        request = Request(scope, receive)

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                logger.info(
                    "http_request",
                    method=request.method,
                    path=request.url.path,
                    status=message.get("status", 0),
                    duration_ms=round(elapsed_ms, 2),
                )
            await send(message)

        await self.app(scope, receive, _send)


def register_middleware(app: FastAPI) -> None:
    # ASGI middleware is applied in reverse order of add_middleware — the last
    # added wraps the outermost. We want: AccessLog (outer) → ReadOnly →
    # RequestID (inner). add_middleware pushes onto a stack, so we add RequestID
    # last to make it the innermost.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(ReadOnlyModeMiddleware)
    app.add_middleware(RequestIDMiddleware)
