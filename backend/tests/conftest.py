"""Shared pytest fixtures.

Three tiers:
  * unit          — pure logic, mocks/fakeredis; no infra dependencies
  * integration   — real Postgres + Redis via docker-compose.test.yml; external HTTP mocked
  * e2e           — full stack incl. Celery eager; external HTTP mocked
  * live          — hits real Meta + Anthropic (opt-in: -m live, RUN_LIVE_TESTS=1)

Conventions:
  - Set DATABASE_URL_TEST / REDIS_URL_TEST env vars before pytest, or rely on
    the docker-compose.test.yml defaults (Postgres 55432, Redis 56379).
  - Tests that need DB/Redis use the explicit fixtures `pg_session`, `redis_client`.
  - Function-scoped DB isolation is by SAVEPOINT rollback (no DROP/RECREATE).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------- Test env
# Make sure tests boot the app with safe defaults (ENV=test bypasses validators
# in app/core/config.py that would otherwise reject empty Meta/JWT secrets).
os.environ.setdefault("ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-min-32-characters-aaaaaaaa")
os.environ.setdefault("META_APP_SECRET", "test-meta-app-secret")
os.environ.setdefault("META_VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("META_ACCESS_TOKEN", "test-access-token")
os.environ.setdefault("META_PHONE_NUMBER_ID", "1234567890")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")

# Test infra defaults (overridable by environment).
_DEFAULT_PG_ASYNC = "postgresql+asyncpg://engageos:engageos@localhost:55432/engageos_test"
_DEFAULT_REDIS = "redis://localhost:56379/0"
os.environ.setdefault("DATABASE_URL", os.environ.get("DATABASE_URL_TEST", _DEFAULT_PG_ASYNC))
os.environ.setdefault("REDIS_URL", os.environ.get("REDIS_URL_TEST", _DEFAULT_REDIS))
os.environ.setdefault("CELERY_BROKER_URL", os.environ["REDIS_URL"])
os.environ.setdefault("CELERY_RESULT_BACKEND", os.environ["REDIS_URL"])

# Register every ORM model so SQLAlchemy can resolve cross-module string
# relationships (e.g. Contact -> "ContactTag") in test processes that do not
# import every module. Without this, mapper configuration fails with a bare
# KeyError for any model whose module wasn't transitively imported.
from app.db.base import import_all_models  # noqa: E402

import_all_models()


# ---------------------------------------------------------------- Path hygiene
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# ---------------------------------------------------------------- App fixture
@pytest.fixture(scope="session")
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app):
    import asyncio

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    # pytest-asyncio creates a fresh event loop per test. The app's global
    # async_engine pools asyncpg connections bound to whichever loop first
    # used them; if a connection outlives its loop, a later test's teardown
    # raises "Event loop is closed". Dispose within this test's still-open
    # loop so no connection leaks across loops.
    #
    # Wrap dispose with a timeout — after many test cycles the pool can
    # enter a state where disposal hangs (e.g. a leaked connection holding
    # the asyncpg transport open). A stuck dispose must not block the next
    # test from starting.
    from app.db.session import async_engine

    try:
        await asyncio.wait_for(async_engine.dispose(), timeout=5.0)
    except (asyncio.TimeoutError, Exception):
        # If dispose times out or fails the pool is already in a bad state;
        # silently move on — the next test's first connect() call will
        # recreate a fresh pool in its own event loop.
        pass


# ---------------------------------------------------------------- Settings reset
@pytest.fixture
def reset_settings():
    """Clear the cached Settings singleton so a test can mutate os.environ
    and re-read config. Restores the previous singleton on teardown."""
    from app.core import config

    prev = config._settings
    config._settings = None
    yield
    config._settings = prev


# ---------------------------------------------------------------- Redis fixtures
@pytest.fixture
def fake_redis():
    """In-memory FakeRedis for unit tests; no infra needed."""
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.FakeRedis(decode_responses=False)


@pytest.fixture
def redis_client():
    """Real Redis connection to docker-compose.test.yml. Skips if not reachable."""
    import redis

    url = os.environ["REDIS_URL"]
    client = redis.Redis.from_url(url, socket_connect_timeout=1)
    try:
        client.ping()
    except Exception:
        pytest.skip(f"Redis not reachable at {url} — start docker-compose.test.yml")
    client.flushdb()
    yield client
    client.flushdb()
    client.close()


# ---------------------------------------------------------------- DB fixtures
def _sync_pg_url() -> str:
    """Derive the sync (psycopg) DSN from DATABASE_URL like Settings does."""
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _pg_reachable(sync_url: str) -> bool:
    try:
        from sqlalchemy import create_engine, text

        eng = create_engine(sync_url, pool_pre_ping=True, future=True)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def _pg_session_ready():
    """Validate Postgres is reachable and run alembic upgrade head once per session."""
    sync_url = _sync_pg_url()
    if not _pg_reachable(sync_url):
        pytest.skip(f"Postgres not reachable at {sync_url} — start docker-compose.test.yml")

    # Run migrations once per test session.
    import subprocess

    env = os.environ.copy()
    env["DATABASE_URL"] = os.environ["DATABASE_URL"]
    proc = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(_BACKEND),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(f"alembic upgrade head failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return sync_url


@pytest.fixture(scope="session")
def pg_engine(_pg_session_ready):
    """Session-scoped sync engine — pooled, expensive to build, cheap to reuse."""
    from sqlalchemy import create_engine

    engine = create_engine(_pg_session_ready, pool_pre_ping=True, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    """Function-scoped sync session with SAVEPOINT rollback isolation.

    Pattern follows SQLAlchemy 2.0 'joined transaction' recipe — every commit
    inside the test becomes a SAVEPOINT release; the outer transaction is
    rolled back at teardown so DB state is restored.
    """
    from sqlalchemy.orm import sessionmaker

    connection = pg_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    nested = connection.begin_nested()

    # Restart SAVEPOINT after each release so the test code can call commit()
    # repeatedly without leaving the outer transaction.
    from sqlalchemy import event

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if trans.nested and trans.parent is not None and not trans.parent.nested:
            nested = connection.begin_nested()

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def committed_db(pg_engine):
    """Real-committing session for tests that drive Celery tasks.

    Celery tasks open their own ``sync_session_factory()`` connection, so
    they cannot see data left uncommitted inside ``pg_session``'s SAVEPOINT.
    Tests that seed data and then invoke a task (reaper, e2e workflows) must
    commit for real. To keep the database clean despite real commits, every
    data table is TRUNCATEd at teardown.
    """
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base

    Session = sessionmaker(
        bind=pg_engine, autoflush=False, expire_on_commit=False
    )
    session = Session()
    yield session
    session.close()
    table_names = ", ".join(
        f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables)
    )
    with pg_engine.begin() as conn:
        conn.execute(
            text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE")
        )


@pytest.fixture
async def async_pg_engine(_pg_session_ready):
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, future=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_pg_session(async_pg_engine):
    """Async session with SAVEPOINT isolation (async equivalent of pg_session)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    connection = await async_pg_engine.connect()
    transaction = await connection.begin()
    Session = async_sessionmaker(bind=connection, class_=AsyncSession, expire_on_commit=False)
    session = Session()
    yield session
    await session.close()
    if transaction.is_active:
        await transaction.rollback()
    await connection.close()


# ---------------------------------------------------------------- Celery eager
@pytest.fixture
def celery_eager():
    """Switch Celery into eager mode so .delay() executes synchronously in-process."""
    try:
        from app.workers import celery_app as celery_mod  # type: ignore[attr-defined]
    except ImportError:
        from app import celery_app as celery_mod

    try:
        app_obj = celery_mod.celery_app  # type: ignore[attr-defined]
    except AttributeError:
        # Fallback: many projects expose the Celery instance as `app`.
        app_obj = celery_mod.app  # type: ignore[attr-defined]
    # autodiscover_tasks is lazy; force task-module import so eager .delay()
    # can resolve every task by name.
    app_obj.loader.import_default_modules()

    prev_eager = app_obj.conf.task_always_eager
    prev_prop = app_obj.conf.task_eager_propagates
    app_obj.conf.task_always_eager = True
    app_obj.conf.task_eager_propagates = True
    yield app_obj
    app_obj.conf.task_always_eager = prev_eager
    app_obj.conf.task_eager_propagates = prev_prop


# ---------------------------------------------------------------- HTTP mocking
@pytest.fixture
def respx_mock():
    """respx router — intercepts all httpx calls. Use in any test that touches
    Claude or Meta clients without going live."""
    respx = pytest.importorskip("respx")
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


# ---------------------------------------------------------------- DB dep override helper
@pytest.fixture
def override_db_dep(app):
    """Replace `get_db_session` FastAPI dependency with a caller-supplied factory."""
    from app.core.dependencies import get_db_session

    overrides = {}

    def _set(factory):
        overrides["factory"] = factory
        app.dependency_overrides[get_db_session] = factory

    yield _set
    app.dependency_overrides.pop(get_db_session, None)


# ---------------------------------------------------------------- Live tier guard
@pytest.fixture
def _require_live_env():
    """Autouse via tests/live/conftest.py — refuses to run live tests unless
    RUN_LIVE_TESTS=1 is set, protecting against accidental real-API calls."""
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("Live tests require RUN_LIVE_TESTS=1 (costs money; sends real WhatsApp messages)")
    # also require the keys to be present
    for key in ("META_ACCESS_TOKEN", "META_PHONE_NUMBER_ID", "ANTHROPIC_API_KEY"):
        if not os.environ.get(key) or os.environ[key].startswith("test-"):
            pytest.skip(f"Live test requires real {key} in environment")
