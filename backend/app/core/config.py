"""
app/core/config.py

Fixes applied:
  Auth-I2  — field_validator rejects default/weak JWT_SECRET in staging/production
  Msg-C3   — model_validator raises if META_APP_SECRET empty in non-dev ENV
             (previously empty string silently bypassed signature verification)
  Msg-M11  — META_VERIFY_TOKEN defaults to "" and fails closed in non-dev ENV
             (previously defaulted to "dev-verify-token", silently accepted in prod)
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Continuity note: fields/properties below this banner (LOG_FORMAT, SERVICE_NAME,
# APP_VERSION, FRONTEND_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND,
# DATABASE_URL_SYNC, cors_origins_list) are preserved from the pre-Phase-4.5
# config so that app/main.py, app/db/session.py, app/core/logging.py, and
# app/celery_app.py keep importing cleanly. Phase 4.5 only changed the auth/meta
# validation surface; nothing else.

_WEAK_JWT_DEFAULT = "change-me-in-production-min-32-characters"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---------------------------------------------------------------- General
    APP_NAME: str = "EngageOS"
    ENV: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["console", "json"] = "console"
    SERVICE_NAME: str = "api"
    APP_VERSION: str = "0.1.0"
    FRONTEND_URL: str = "http://localhost:3000"

    # -------------------------------------------------------------- Database
    DATABASE_URL: str = "postgresql+asyncpg://engageos:engageos@localhost:5432/engageos"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # DSD §11 — "Database Failure → read-only emergency mode".
    # P1.3 decision: explicit operator-driven flag is the engagement
    # mechanism. When true, ReadOnlyModeMiddleware returns 503 for all
    # mutating HTTP methods (POST/PUT/PATCH/DELETE) while GET stays live,
    # and /health reports degraded. Automatic engagement on repeated DB
    # connection failures is deliberately deferred (would require a
    # per-request DB probe or pool-error hook — too invasive for this
    # scope); documented as a follow-up in the §11-resilience memory.
    READ_ONLY_MODE: bool = False

    # -------------------------------------------------------- Market Pipeline
    # P0: When True, the backend trusts the listener's precomputed Pass B-D
    # output and skips the internal classifier. Flipped to False after the
    # Python extractor port (P8) passes the golden-set parity gate.
    MARKET_TRUST_LISTENER: bool = True
    # When True (default), market search uses PostgreSQL full-text search
    # (websearch_to_tsquery + ts_rank). Flip to False to revert to ilike scan.
    MARKET_SEARCH_USE_FTS: bool = True
    # Hours a structured fingerprint stays hot in Redis before a re-post
    # creates a new row rather than bumping seen_count.
    MARKET_FINGERPRINT_WINDOW_HOURS: int = 3

    # --------------------------------------------------------------- Caching
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    # ------------------------------------------------------------------- JWT
    JWT_SECRET: str = _WEAK_JWT_DEFAULT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --------------------------------------------------------------- Meta WA
    # Msg-M11 fix: default empty string — validation below rejects this in
    # non-development environments so the system fails closed rather than
    # silently accepting any verify-token handshake in production.
    META_VERIFY_TOKEN: str = ""
    META_APP_SECRET: str = ""
    META_ACCESS_TOKEN: str = ""
    META_PHONE_NUMBER_ID: str = ""
    # WhatsApp Business Account ID — required for the message-template
    # management API (template submit/status). Empty in dev/test: the
    # template service then keeps the local row PENDING and skips the
    # remote call rather than failing.
    META_WABA_ID: str = ""
    # Graph API version pin. Meta expires each version ~2 years after release
    # (v19.0 reached EOL 2026-05-21). Keep this on a currently-supported
    # release; v25.0 (released 2026-02-18) is the latest. The send / template /
    # webhook contracts are unchanged across v19→v25, so bumps are low-risk.
    META_API_VERSION: str = "v25.0"
    # Outbound rate limit guard (messages/second) — Meta enforces ~80/s per WABA
    META_SEND_RATE_LIMIT: int = 60

    # ---------------------------------------------------------- Anthropic / Claude
    ANTHROPIC_API_KEY: str = ""
    # Model for bulk (first-pass) drafting — fast and cheap (Haiku 4.5).
    AI_MODEL_BULK: str = "claude-haiku-4-5-20251001"
    # Model for escalation decisions — accurate and thorough (Sonnet 4.6).
    AI_MODEL_ESCALATION: str = "claude-sonnet-4-6"
    AI_MAX_OUTPUT_TOKENS: int = 512
    AI_REQUEST_TIMEOUT_SECONDS: int = 15
    AI_AUTO_SEND_CONFIDENCE: float = 0.85
    AI_ESCALATION_CONFIDENCE_FLOOR: float = 0.50
    # Number of recent messages to include in the LLM context window.
    # Set high (500) so the full chat history is provided when crafting replies.
    # The client memory file carries accumulated context for anything beyond this.
    AI_HISTORY_MESSAGE_LIMIT: int = 500
    # When True (default), the AI orchestrator loads and updates per-contact
    # memory files on the Railway volume (/app/media/memories/).
    AI_CLIENT_MEMORY_ENABLED: bool = True

    # ---------------------------------------------------------------- Celery
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_TASK_ALWAYS_EAGER: bool = False  # set True in test env only

    # -------------------------------------------------------------- Locking
    CONVERSATION_LOCK_TTL_SECONDS: int = 120

    # ---------------------------------------------------------------- CORS
    # Stored as a plain string so a bare value (e.g. "https://app.example.com"
    # or a comma-separated list) works as a Railway env var. pydantic-settings
    # would otherwise JSON-decode a list[str] field and raise SettingsError on
    # a non-JSON value. Consumers read the parsed form via cors_origins_list.
    CORS_ORIGINS: str = "http://localhost:3000"

    # ---------------------------------------------------------------- Validators

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """
        Auth-I2 fix: the previous implementation accepted the weak default
        value in staging and production because no validator existed.
        A misconfigured deployment would issue tokens signed with a publicly
        known secret.

        Rule: in staging or production, JWT_SECRET must differ from the
        default and be at least 32 characters long.
        """
        env = os.getenv("ENV", "development")
        if env in ("staging", "production"):
            if v == _WEAK_JWT_DEFAULT:
                raise ValueError(
                    "JWT_SECRET is set to the insecure default value. "
                    "Set a cryptographically random secret (≥32 chars) "
                    f"before deploying to {env}."
                )
            if len(v) < 32:
                raise ValueError(
                    f"JWT_SECRET must be at least 32 characters in {env}. "
                    f"Current length: {len(v)}."
                )
        return v

    @field_validator("META_VERIFY_TOKEN")
    @classmethod
    def validate_meta_verify_token(cls, v: str) -> str:
        """
        Msg-M11 fix: empty META_VERIFY_TOKEN is rejected in non-development
        environments. Without this, a misconfigured production instance would
        accept any GET handshake from Meta (or an attacker).
        """
        env = os.getenv("ENV", "development")
        if env in ("staging", "production") and not v:
            raise ValueError(
                "META_VERIFY_TOKEN must be configured in staging/production. "
                "An empty verify token will fail the Meta webhook handshake."
            )
        return v

    @field_validator("CELERY_BROKER_URL", mode="before")
    @classmethod
    def _default_broker(cls, v: str | None, info) -> str:
        if v:
            return v
        return info.data.get("REDIS_URL", "redis://localhost:6379/0")

    @field_validator("CELERY_RESULT_BACKEND", mode="before")
    @classmethod
    def _default_backend(cls, v: str | None, info) -> str:
        if v:
            return v
        return info.data.get("REDIS_URL", "redis://localhost:6379/0")

    @property
    def DATABASE_URL_SYNC(self) -> str:  # noqa: N802
        """Sync DSN derived from DATABASE_URL — used by Alembic and Celery tasks."""
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    @property
    def DATABASE_URL_ASYNC(self) -> str:  # noqa: N802
        """Async DSN derived from DATABASE_URL — used by the FastAPI engine.

        Railway's managed Postgres exposes ${{Postgres.DATABASE_URL}} as a
        plain ``postgresql://`` URL with no async driver. ``create_async_engine``
        requires an async driver, so normalize any sync/plain form to
        ``postgresql+asyncpg://``. Pass through if already async.
        """
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return url
        if url.startswith("postgresql+psycopg://"):
            return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS_ORIGINS as a list, accepting both list and comma-separated string forms."""
        if isinstance(self.CORS_ORIGINS, list):
            return [o.strip() for o in self.CORS_ORIGINS if o and o.strip()]
        return [o.strip() for o in str(self.CORS_ORIGINS).split(",") if o.strip()]

    @model_validator(mode="after")
    def validate_anthropic_api_key(self) -> Settings:
        """Anthropic API key is required in staging/production — the AI cascade
        cannot make any decisions without it."""
        if self.ENV in ("staging", "production") and not self.ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY must be set in staging/production. "
                "Without it, the AI cascade cannot make any decisions."
            )
        return self

    @model_validator(mode="after")
    def validate_meta_app_secret(self) -> Settings:
        """
        Msg-C3 fix: META_APP_SECRET being empty string previously caused the
        signature verification logic to silently skip validation — any unsigned
        POST would be accepted. Now the application refuses to start in
        staging/production without a configured secret.
        """
        if self.ENV in ("staging", "production") and not self.META_APP_SECRET:
            raise ValueError(
                "META_APP_SECRET must be set in staging/production. "
                "Without it, incoming webhook signature verification is "
                "disabled and the endpoint accepts unauthenticated requests."
            )
        return self


# Module-level singleton — import via get_settings() to allow override in tests.
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
