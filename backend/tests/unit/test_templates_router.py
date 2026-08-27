"""Router-level tests for templates endpoints (P0.2).

Service is mocked so the test isolates router wiring + role gating.
Full DB-backed coverage lives in tests/integration/test_api_smoke.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import (
    get_current_user_claims,
    get_current_user_db,
    get_db_session,
)


def _make_template(**ov):
    base = MagicMock()
    base.id = ov.get("id", uuid.uuid4())
    base.meta_template_id = ov.get("meta_template_id", None)
    base.name = ov.get("name", "welcome_msg")
    base.status = ov.get("status", "pending")
    base.category = ov.get("category", "utility")
    base.language = ov.get("language", "en")
    base.body = ov.get("body", "Hello there")
    base.created_at = ov.get("created_at", datetime.now(UTC))
    base.updated_at = ov.get("updated_at", datetime.now(UTC))
    return base


@pytest.fixture(autouse=True)
def stub_db_session(app):
    async def _fake_session():
        yield AsyncMock()
    app.dependency_overrides[get_db_session] = _fake_session
    yield
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def override_user(app):
    user_id = uuid.uuid4()

    def _set(role: str = "agent") -> uuid.UUID:
        async def _claims() -> dict:
            return {"sub": str(user_id), "role": role, "iat": 0, "exp": 9999999999}

        user = MagicMock()
        user.id = user_id
        user.role = role

        async def _user() -> object:
            return user

        app.dependency_overrides[get_current_user_claims] = _claims
        app.dependency_overrides[get_current_user_db] = _user
        return user_id

    yield _set
    app.dependency_overrides.pop(get_current_user_claims, None)
    app.dependency_overrides.pop(get_current_user_db, None)


def _patch_service(monkeypatch, fake):
    from app.modules.templates import router as mod
    monkeypatch.setattr(mod, "TemplateService", lambda _session: fake)


@pytest.mark.asyncio
async def test_list_requires_authentication(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/templates")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_returns_page_envelope_for_agent(app, override_user, monkeypatch):
    override_user("agent")
    fake = MagicMock()
    fake.list_templates = AsyncMock(return_value=([_make_template(), _make_template()], 2))
    _patch_service(monkeypatch, fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/api/v1/templates?page=1&page_size=10&status=pending",
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and len(body["items"]) == 2
    assert fake.list_templates.await_args.kwargs["status"] == "pending"


@pytest.mark.asyncio
async def test_submit_is_admin_only(app, override_user, monkeypatch):
    override_user("agent")
    fake = MagicMock()
    fake.submit_template = AsyncMock(return_value=_make_template())
    _patch_service(monkeypatch, fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/templates/submit",
            json={"name": "promo", "category": "marketing", "language": "en", "body": "Hi"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 403
    fake.submit_template.assert_not_called()


@pytest.mark.asyncio
async def test_submit_admin_returns_201(app, override_user, monkeypatch):
    override_user("admin")
    created = _make_template(name="promo", status="pending")
    fake = MagicMock()
    fake.submit_template = AsyncMock(return_value=created)
    _patch_service(monkeypatch, fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/templates/submit",
            json={"name": "Promo Blast", "category": "marketing", "language": "en", "body": "Hi"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "promo"
    # name normalized to snake_case lowercase before reaching the service
    assert fake.submit_template.await_args.kwargs["name"] == "promo_blast"


@pytest.mark.asyncio
async def test_sync_is_admin_only(app, override_user, monkeypatch):
    override_user("agent")
    fake = MagicMock()
    fake.sync_status_from_meta = AsyncMock(return_value=_make_template())
    _patch_service(monkeypatch, fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/templates/{uuid.uuid4()}/sync",
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sync_admin_returns_200(app, override_user, monkeypatch):
    override_user("admin")
    tmpl = _make_template(status="approved")
    fake = MagicMock()
    fake.sync_status_from_meta = AsyncMock(return_value=tmpl)
    _patch_service(monkeypatch, fake)

    tid = uuid.uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            f"/api/v1/templates/{tid}/sync",
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
