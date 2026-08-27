"""Database engines and session factories.

Two engines:
  - Async (`asyncpg`) for FastAPI request handlers.
  - Sync (`psycopg`) for Celery tasks and Alembic migrations.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

_settings = get_settings()

async_engine = create_async_engine(
    _settings.DATABASE_URL_ASYNC,
    pool_pre_ping=True,
    future=True,
    pool_timeout=5,
    connect_args={
        "timeout": 10,
        "command_timeout": 30,
    },
)

async_session_factory = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

sync_engine = create_engine(
    _settings.DATABASE_URL_SYNC,
    pool_pre_ping=True,
    future=True,
)

sync_session_factory = sessionmaker(
    sync_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
