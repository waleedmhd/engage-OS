"""Domain exception hierarchy + FastAPI handlers.

Each external-failure category gets its own type so that integrations can raise
specific errors and routers don't need to know HTTP status codes.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class EngageOSError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str | None = None, *, details: dict | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details or {}


class AuthError(EngageOSError):
    status_code = 401
    code = "auth_error"


class AuthenticationError(AuthError):
    """Authentication-specific failure (invalid credentials, expired/revoked token).

    Subclass of AuthError so existing handlers and isinstance(exc, AuthError)
    checks keep working. Phase 4.5 auth/service.py and core/security.py raise
    this with human-readable messages.
    """

    code = "authentication_error"


class ForbiddenError(EngageOSError):
    status_code = 403
    code = "forbidden"


class PermissionError(ForbiddenError):
    """Domain permission denial. Imported by conversations service for role/lock gates."""

    code = "permission_denied"


class NotFoundError(EngageOSError):
    status_code = 404
    code = "not_found"


class ConflictError(EngageOSError):
    status_code = 409
    code = "conflict"


class StateTransitionError(ConflictError):
    """Illegal state-machine transition. 409 like ConflictError."""

    code = "state_transition_error"


class ConcurrentModificationError(ConflictError):
    """Optimistic-concurrency conflict (UPDATE WHERE state=expected matched 0 rows)."""

    code = "concurrent_modification"


class ValidationError(EngageOSError):
    status_code = 422
    code = "validation_error"


class MessagingDispatchError(EngageOSError):
    status_code = 502
    code = "messaging_dispatch_error"


class MetaAPIError(EngageOSError):
    status_code = 502
    code = "meta_api_error"


class AIProviderError(EngageOSError):
    """Generic AI provider failure (Anthropic API, transport, etc.).

    Carries a ``retryable`` flag consumed by the Celery retry policy in
    ``ai.tasks``. Transient errors (timeout, rate-limit, 5xx, connection)
    are retryable; schema/validation errors are not.
    """

    status_code = 502
    code = "ai_provider_error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message, details=details)
        self.retryable = retryable


class AIProviderTimeoutError(AIProviderError):
    """Anthropic API request timed out. Always retryable."""

    code = "ai_provider_timeout"

    def __init__(self, message: str | None = None, *, details: dict | None = None) -> None:
        super().__init__(message, details=details, retryable=True)


class AIProviderInvalidResponseError(AIProviderError):
    """Anthropic returned a response that failed tool-use schema validation."""

    code = "ai_provider_invalid_response"


class ConversationLockError(EngageOSError):
    status_code = 423
    code = "conversation_locked"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(EngageOSError)
    async def _engageos_handler(request: Request, exc: EngageOSError) -> JSONResponse:
        logger.warning(
            "domain_exception",
            code=exc.code,
            message=exc.message,
            path=request.url.path,
            details=exc.details,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )
