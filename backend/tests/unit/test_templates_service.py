"""Unit tests for the Templates module service + constants (P0.2).

Pure service/repo tests share a single rolled-back async session
(`async_pg_session`); no Celery task or HTTP endpoint is exercised here,
so the committed_db rule does not apply. The Meta client is injected as
a mock so no network call is made.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.templates.constants import (
    TemplateStatus,
    map_meta_status,
)
from app.modules.templates.models import Template
from app.modules.templates.service import TemplateService

# ----------------------------------------------------------- constants

@pytest.mark.parametrize(
    "meta,expected",
    [
        ("APPROVED", TemplateStatus.APPROVED),
        ("approved", TemplateStatus.APPROVED),
        ("PENDING", TemplateStatus.PENDING),
        ("REJECTED", TemplateStatus.REJECTED),
        ("PAUSED", TemplateStatus.DISABLED),
        ("FLAGGED", TemplateStatus.DISABLED),
        (None, TemplateStatus.PENDING),
        ("", TemplateStatus.PENDING),
    ],
)
def test_map_meta_status(meta, expected):
    assert map_meta_status(meta) is expected


def _configure(service: TemplateService, *, enabled: bool) -> None:
    service._settings = SimpleNamespace(
        META_WABA_ID="waba" if enabled else "",
        META_ACCESS_TOKEN="tok" if enabled else "",
    )


# ----------------------------------------------------------- submit

@pytest.mark.asyncio
async def test_submit_not_configured_creates_pending_no_meta_call(async_pg_session):
    meta = MagicMock()
    svc = TemplateService(async_pg_session, meta_client=meta)
    _configure(svc, enabled=False)

    tmpl = await svc.submit_template(
        name="welcome_msg", category="utility", language="en", body="Hi {{1}}"
    )

    assert tmpl.status == TemplateStatus.PENDING.value
    assert tmpl.meta_template_id is None
    meta.submit_message_template.assert_not_called()


@pytest.mark.asyncio
async def test_submit_configured_calls_meta_and_maps_status(async_pg_session):
    meta = MagicMock()
    meta.submit_message_template.return_value = {"id": "meta-123", "status": "APPROVED"}
    svc = TemplateService(async_pg_session, meta_client=meta)
    _configure(svc, enabled=True)

    tmpl = await svc.submit_template(
        name="promo_blast", category="marketing", language="en", body="Sale!"
    )

    meta.submit_message_template.assert_called_once()
    refreshed = await async_pg_session.get(Template, tmpl.id)
    assert refreshed.status == TemplateStatus.APPROVED.value
    assert refreshed.meta_template_id == "meta-123"


@pytest.mark.asyncio
async def test_submit_duplicate_name_raises_conflict(async_pg_session):
    svc = TemplateService(async_pg_session, meta_client=MagicMock())
    _configure(svc, enabled=False)
    await svc.submit_template(
        name="dupe", category="utility", language="en", body="x"
    )
    with pytest.raises(ConflictError):
        await svc.submit_template(
            name="dupe", category="utility", language="en", body="y"
        )


# ----------------------------------------------------------- sync

@pytest.mark.asyncio
async def test_sync_status_from_meta_updates_local_row(async_pg_session):
    meta = MagicMock()
    meta.get_message_template.return_value = {"status": "APPROVED"}
    svc = TemplateService(async_pg_session, meta_client=meta)

    tmpl = Template(
        id=uuid.uuid4(),
        name="needs_sync",
        status=TemplateStatus.PENDING.value,
        category="utility",
        language="en",
        meta_template_id="remote-1",
    )
    async_pg_session.add(tmpl)
    await async_pg_session.flush()

    updated = await svc.sync_status_from_meta(tmpl.id)
    assert updated.status == TemplateStatus.APPROVED.value
    meta.get_message_template.assert_called_once_with(meta_template_id="remote-1")


@pytest.mark.asyncio
async def test_sync_status_without_remote_id_raises(async_pg_session):
    svc = TemplateService(async_pg_session, meta_client=MagicMock())
    tmpl = Template(
        id=uuid.uuid4(),
        name="no_remote",
        status=TemplateStatus.PENDING.value,
        category="utility",
        language="en",
        meta_template_id=None,
    )
    async_pg_session.add(tmpl)
    await async_pg_session.flush()

    with pytest.raises(NotFoundError):
        await svc.sync_status_from_meta(tmpl.id)


@pytest.mark.asyncio
async def test_sync_unknown_template_raises(async_pg_session):
    svc = TemplateService(async_pg_session, meta_client=MagicMock())
    with pytest.raises(NotFoundError):
        await svc.sync_status_from_meta(uuid.uuid4())


# ----------------------------------------------------------- list

@pytest.mark.asyncio
async def test_list_templates_paginates_and_filters(async_pg_session):
    svc = TemplateService(async_pg_session, meta_client=MagicMock())
    _configure(svc, enabled=False)
    for i in range(3):
        await svc.submit_template(
            name=f"tmpl_{i}", category="utility", language="en", body="b"
        )

    items, total = await svc.list_templates(page=1, page_size=2)
    assert total == 3
    assert len(items) == 2

    pending, total_p = await svc.list_templates(
        page=1, page_size=50, status=TemplateStatus.PENDING.value
    )
    assert total_p == 3
    assert all(t.status == TemplateStatus.PENDING.value for t in pending)
