"""DSD §11 degraded-mode tests (P1.3).

- redis_healthy() never raises and reflects PING outcome.
- Redis down → send_outbound_message_task reschedules (Retry), does NOT
  mark the message FAILED.
- Redis down → process_campaign_batch_task reschedules before any send.
- READ_ONLY_MODE → 503 on mutating verbs, 200 on GET, /webhooks/* exempt,
  /health reports degraded.
"""

from __future__ import annotations

import uuid

import pytest
from celery.exceptions import Retry
from httpx import ASGITransport, AsyncClient

from app.core import redis as redis_mod
from app.core.config import get_settings
from app.modules.campaigns import tasks as campaign_tasks
from app.modules.messaging import tasks as msg_tasks

# Calling `.run()` directly (no worker request context) means `self.retry`
# cannot actually reschedule: Celery re-raises the provided `exc` instead of
# `Retry`. Either way the task aborts WITHOUT completing — which is the
# property we assert (the message is never marked FAILED / dropped).
_PAUSE_EXC = (Retry, RuntimeError)


# ----------------------------------------------------------- redis_healthy

def test_redis_healthy_true_on_ping(monkeypatch):
    class _C:
        def ping(self):
            return True

        def close(self):
            pass

    monkeypatch.setattr(
        redis_mod.redis_sync.Redis, "from_url", classmethod(lambda cls, *a, **k: _C())
    )
    assert redis_mod.redis_healthy() is True


def test_redis_healthy_false_and_never_raises(monkeypatch):
    def _boom(*a, **k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(
        redis_mod.redis_sync.Redis, "from_url", classmethod(lambda cls, *a, **k: _boom())
    )
    assert redis_mod.redis_healthy() is False


# -------------------------------------------- outbound paused when redis down

def test_send_outbound_paused_does_not_fail_message(monkeypatch):
    monkeypatch.setattr(msg_tasks, "redis_healthy", lambda: False)
    called = {}
    monkeypatch.setattr(
        msg_tasks,
        "MessageRepository",
        lambda _s: called.setdefault("repo_built", True),
    )

    with pytest.raises(_PAUSE_EXC):
        msg_tasks.send_outbound_message_task.run(str(uuid.uuid4()))

    # No DB work happened — message never marked FAILED, stays QUEUED.
    assert "repo_built" not in called


def test_campaign_batch_paused_when_redis_down(monkeypatch):
    monkeypatch.setattr(campaign_tasks, "redis_healthy", lambda: False)
    with pytest.raises(_PAUSE_EXC):
        campaign_tasks.process_campaign_batch_task.run(
            str(uuid.uuid4()), [str(uuid.uuid4())]
        )


# --------------------------------------------------- read-only middleware

@pytest.fixture
def read_only(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "READ_ONLY_MODE", True)
    yield


@pytest.mark.asyncio
async def test_read_only_blocks_writes_allows_reads(app, read_only):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        post = await ac.post("/api/v1/settings/x", json={"value": {}})
        get = await ac.get("/health")
    assert post.status_code == 503
    assert post.json()["error"]["code"] == "read_only_mode"
    assert get.status_code == 200


@pytest.mark.asyncio
async def test_health_reports_degraded(app, read_only):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
    body = r.json()
    assert body["status"] == "degraded"
    assert body["read_only"] is True


@pytest.mark.asyncio
async def test_health_ok_when_not_read_only(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
    body = r.json()
    assert body["status"] == "ok"
    assert body["read_only"] is False


@pytest.mark.asyncio
async def test_webhook_exempt_from_read_only(app, read_only):
    """Meta webhook must still be reachable (not 503) so Meta doesn't enter
    a retry storm; DB-outage handling is deferred to the worker."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/webhooks/meta", json={})
    assert r.status_code != 503


@pytest.mark.asyncio
async def test_settings_operational_exempt_from_read_only(app, read_only):
    """The endpoint that disables read-only mode must remain reachable while
    read-only mode is engaged — otherwise operators would have to redeploy
    to flip the env flag back off."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put(
            "/api/v1/settings/operational",
            json={"read_only_mode": {"enabled": False}},
        )
    # 401/403 from auth is fine — what matters is we did NOT 503 at the
    # middleware layer (the request was allowed through to the handler).
    assert r.status_code != 503


# ---------------------------------- DB-backed read-only flag (piece 2)

from app.core import middleware as mw_mod  # noqa: E402


@pytest.fixture
def reset_ro_cache():
    mw_mod._RO_CACHE["value"] = False
    mw_mod._RO_CACHE["fetched_at"] = 0.0
    yield
    mw_mod._RO_CACHE["value"] = False
    mw_mod._RO_CACHE["fetched_at"] = 0.0


@pytest.mark.asyncio
async def test_db_flag_blocks_writes_with_env_off(
    app, monkeypatch, reset_ro_cache
):
    # env flag OFF; DB flag ON -> still 503 on writes.
    monkeypatch.setattr(get_settings(), "READ_ONLY_MODE", False)

    async def _db_on() -> bool:
        return True

    monkeypatch.setattr(mw_mod, "_fetch_db_read_only", _db_on)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        post = await ac.post("/api/v1/settings/x", json={"value": {}})
        get = await ac.get("/health")
    assert post.status_code == 503
    assert post.json()["error"]["code"] == "read_only_mode"
    assert get.status_code == 200


@pytest.mark.asyncio
async def test_db_flag_fetch_failure_does_not_block(
    app, monkeypatch, reset_ro_cache
):
    monkeypatch.setattr(get_settings(), "READ_ONLY_MODE", False)

    async def _boom() -> bool:
        raise RuntimeError("settings DB unreachable")

    monkeypatch.setattr(mw_mod, "_fetch_db_read_only", _boom)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        post = await ac.post("/api/v1/settings/x", json={"value": {}})
    assert post.status_code != 503


@pytest.mark.asyncio
async def test_db_flag_cached_within_ttl(app, monkeypatch, reset_ro_cache):
    monkeypatch.setattr(get_settings(), "READ_ONLY_MODE", False)
    calls = {"n": 0}

    async def _count() -> bool:
        calls["n"] += 1
        return False

    monkeypatch.setattr(mw_mod, "_fetch_db_read_only", _count)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post("/api/v1/settings/x", json={"value": {}})
        await ac.post("/api/v1/settings/x", json={"value": {}})
    # Second mutating request within the 10s TTL must reuse the cached value.
    assert calls["n"] == 1
