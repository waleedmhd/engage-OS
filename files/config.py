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
    ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # -------------------------------------------------------------- Database
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # --------------------------------------------------------------- Caching
    REDIS_URL: str = "redis://localhost:6379/0"

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
    META_API_VERSION: str = "v19.0"
    # Outbound rate limit guard (messages/second) — Meta enforces ~80/s per WABA
    META_SEND_RATE_LIMIT: int = 60

    # ---------------------------------------------------------------- Base44
    BASE44_API_KEY: str = ""
    BASE44_ENDPOINT: str = ""
    BASE44_TIMEOUT_SECONDS: int = 10

    # ---------------------------------------------------------------- Celery
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_TASK_ALWAYS_EAGER: bool = False  # set True in test env only

    # -------------------------------------------------------------- Locking
    CONVERSATION_LOCK_TTL_SECONDS: int = 120

    # ---------------------------------------------------------------- CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

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

    @model_validator(mode="after")
    def validate_meta_app_secret(self) -> "Settings":
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
