"""Tests for the CSV import feature.

Two layers:
  - Pure parser tests (`parse_csv`) — no DB, no FastAPI
  - Router tests with a mocked ContactService — confirm role gate, file
    handling, and receipt envelope
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import (
    get_current_user_claims,
    get_current_user_db,
    get_db_session,
)
from app.modules.contacts.import_csv import (
    ParsedContactRow,
    ParseError,
    parse_csv,
)
from app.modules.contacts.schemas import ContactImportReceipt

# ============================================================ parser tests

def _consume(raw: bytes, **kwargs) -> list:
    return list(parse_csv(raw, **kwargs))


def test_parse_csv_happy_path():
    raw = (
        b"phone,name,company\n"
        b"+15550001111,Acme,AcmeCo\n"
        b"+15550002222,Beta,BetaCo\n"
    )
    out = _consume(raw)
    assert len(out) == 2
    assert all(isinstance(r, ParsedContactRow) for r in out)
    # Canonical wa_id form: leading '+' stripped so the row matches Meta's
    # bare-wa_id inbound and never spawns a duplicate contact.
    assert out[0].phone == "15550001111"
    assert out[0].name == "Acme"


def test_parse_csv_header_normalizes_case_and_whitespace():
    raw = b" Phone , NAME ,Company\n+15550001111,Acme,AcmeCo\n"
    out = _consume(raw)
    assert len(out) == 1
    assert isinstance(out[0], ParsedContactRow)
    assert out[0].name == "Acme"


def test_parse_csv_missing_phone_column_returns_fatal_error():
    raw = b"name,company\nAcme,AcmeCo\n"
    out = _consume(raw)
    assert len(out) == 1
    assert isinstance(out[0], ParseError)
    assert out[0].error == "csv_missing_phone_column"


def test_parse_csv_phone_normalized_strips_dashes_spaces_and_plus():
    raw = b"phone\n+1 (555) 000-1111\n"
    out = _consume(raw)
    assert len(out) == 1
    assert isinstance(out[0], ParsedContactRow)
    # '+', spaces, parens and dashes all stripped → canonical wa_id digits.
    assert out[0].phone == "15550001111"


def test_parse_csv_invalid_phone_yields_parse_error():
    raw = b"phone\nnot-a-phone\n"
    out = _consume(raw)
    assert len(out) == 1
    assert isinstance(out[0], ParseError)
    assert out[0].error == "invalid_phone_format"


def test_parse_csv_skips_empty_rows_silently():
    raw = b"phone,name\n+15550001111,Acme\n,\n+15550002222,Beta\n"
    out = _consume(raw)
    # Empty middle row is skipped — no ParseError emitted for it.
    assert len(out) == 2
    assert all(isinstance(r, ParsedContactRow) for r in out)


def test_parse_csv_missing_phone_value_yields_error():
    raw = b"phone,name\n,Acme\n"
    out = _consume(raw)
    assert len(out) == 1
    assert isinstance(out[0], ParseError)
    assert out[0].error == "missing_phone"


def test_parse_csv_respects_max_rows_cap():
    rows = b"phone\n" + b"\n".join(
        f"+1555000{i:04d}".encode() for i in range(20)
    ) + b"\n"
    out = _consume(rows, max_rows=5)
    parsed = [r for r in out if isinstance(r, ParsedContactRow)]
    assert len(parsed) == 5


def test_parse_csv_handles_utf8_bom():
    raw = b"\xef\xbb\xbfphone,name\n+15550001111,Acme\n"
    out = _consume(raw)
    assert len(out) == 1
    assert isinstance(out[0], ParsedContactRow)


def test_parse_csv_empty_file_yields_nothing():
    assert _consume(b"") == []


# ============================================================ router tests

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

    def _set(role: str = "admin") -> uuid.UUID:
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


@pytest.mark.asyncio
async def test_import_endpoint_requires_admin(app, override_user):
    """Non-admin agents cannot bulk import — admin-only operation."""
    override_user("agent")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts/import",
            files={"file": ("contacts.csv", io.BytesIO(b"phone\n+15550001111\n"), "text/csv")},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_import_endpoint_returns_receipt(app, override_user, monkeypatch):
    """Admin upload returns a 200 receipt with counts."""
    override_user("admin")

    fake_receipt = ContactImportReceipt(
        total_rows=3, created=2, updated=1, skipped=0, errors=[]
    )
    fake_service = MagicMock()
    fake_service.import_csv = AsyncMock(return_value=fake_receipt)

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactService", lambda _s: fake_service
    )

    csv_body = b"phone,name\n+15550001111,A\n+15550002222,B\n+15550003333,C\n"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts/import",
            files={"file": ("c.csv", io.BytesIO(csv_body), "text/csv")},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 2
    assert body["updated"] == 1
    assert body["skipped"] == 0

    # Service got the raw bytes and the actor id from the JWT claim.
    call = fake_service.import_csv.await_args
    assert call.kwargs["raw_bytes"] == csv_body


@pytest.mark.asyncio
async def test_import_rejects_oversized_payload(app, override_user, monkeypatch):
    """Files >10MB get a 413 before the service is even invoked."""
    override_user("admin")

    # Patch the service so we can detect (or rather, NOT detect) any call.
    fake_service = MagicMock()
    fake_service.import_csv = AsyncMock()

    from app.modules.contacts import router as contacts_router_module
    monkeypatch.setattr(
        contacts_router_module, "ContactService", lambda _s: fake_service
    )
    # Lower the cap so the test stays cheap.
    monkeypatch.setattr(contacts_router_module, "_MAX_CSV_BYTES", 1024)

    big_body = b"phone\n" + (b"+15550001111\n" * 200)  # well over 1KB
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/contacts/import",
            files={"file": ("c.csv", io.BytesIO(big_body), "text/csv")},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 413
    assert fake_service.import_csv.await_count == 0
