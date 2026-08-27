"""CampaignService integration tests (async path).

Exercises create → validate (success + compliance failures) → launch →
cancel → report → update against real Postgres.
"""
from __future__ import annotations

import uuid

import pytest

from app.modules.campaigns.constants import CampaignStatus
from app.modules.campaigns.schemas import (
    AudienceFilter,
    CampaignCreateRequest,
    CampaignUpdateRequest,
)
from app.modules.campaigns.service import CampaignService
from app.modules.categorization.models import ContactTag, Tag
from app.modules.contacts.models import Contact
from app.modules.templates.models import Template


async def _template(session, status="approved"):
    t = Template(
        id=uuid.uuid4(), name=f"tmpl_{uuid.uuid4().hex[:8]}",
        status=status, category="marketing", language="en",
    )
    session.add(t)
    await session.flush()
    return t


async def _contacts(session, n=3):
    out = []
    for i in range(n):
        c = Contact(
            id=uuid.uuid4(), phone=f"+1999{uuid.uuid4().int % 10_000_000:07d}",
            name=f"C{i}", status="active", marketing_opt_out=False,
        )
        session.add(c)
        out.append(c)
    await session.flush()
    return out


@pytest.mark.asyncio
async def test_create_validate_launch_cancel_report(async_pg_session):
    await _contacts(async_pg_session, 3)
    template = await _template(async_pg_session)
    svc = CampaignService(async_pg_session)

    campaign = await svc.create_campaign(
        CampaignCreateRequest(template_id=template.id, name="Promo", type="immediate"),
        actor_id=None,
    )
    assert campaign.status == CampaignStatus.DRAFT.value

    result = await svc.validate_campaign(campaign.id, actor_id=None)
    assert result.ok is True
    assert result.recipient_count == 3

    launched = await svc.launch_campaign(campaign.id, actor_id=None)
    assert launched.status == CampaignStatus.QUEUED.value

    report = await svc.get_report(campaign.id)
    assert report is not None

    cancelled = await svc.cancel_campaign(campaign.id, actor_id=None)
    assert cancelled.status == CampaignStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_validate_fails_on_unapproved_template(async_pg_session):
    await _contacts(async_pg_session, 2)
    template = await _template(async_pg_session, status="pending")
    svc = CampaignService(async_pg_session)

    campaign = await svc.create_campaign(
        CampaignCreateRequest(template_id=template.id, name="Bad", type="immediate"),
        actor_id=None,
    )
    result = await svc.validate_campaign(campaign.id, actor_id=None)
    assert result.ok is False
    assert any("template" in e.code for e in result.errors)


@pytest.mark.asyncio
async def test_validate_fails_with_no_recipients(async_pg_session):
    template = await _template(async_pg_session)
    svc = CampaignService(async_pg_session)

    campaign = await svc.create_campaign(
        CampaignCreateRequest(template_id=template.id, name="Empty", type="immediate"),
        actor_id=None,
    )
    result = await svc.validate_campaign(campaign.id, actor_id=None)
    assert result.ok is False
    assert result.recipient_count == 0


@pytest.mark.asyncio
async def test_update_campaign_in_draft(async_pg_session):
    template = await _template(async_pg_session)
    svc = CampaignService(async_pg_session)
    campaign = await svc.create_campaign(
        CampaignCreateRequest(template_id=template.id, name="Old", type="immediate"),
        actor_id=None,
    )
    updated = await svc.update_campaign(
        campaign.id, CampaignUpdateRequest(name="New"), actor_id=None
    )
    assert updated.name == "New"


@pytest.mark.asyncio
async def test_audience_filter_with_contact_ids(async_pg_session):
    """contact_ids in audience_filter limits audience to those contacts."""
    contacts = await _contacts(async_pg_session, 5)
    template = await _template(async_pg_session)
    svc = CampaignService(async_pg_session)

    target_ids = [contacts[0].id, contacts[2].id]
    campaign = await svc.create_campaign(
        CampaignCreateRequest(
            template_id=template.id,
            name="Targeted",
            type="immediate",
            audience_filter=AudienceFilter(contact_ids=target_ids),
        ),
        actor_id=None,
    )
    result = await svc.validate_campaign(campaign.id, actor_id=None)
    assert result.ok is True
    assert result.recipient_count == 2


@pytest.mark.asyncio
async def test_audience_filter_contact_ids_composes_with_tags(async_pg_session):
    """contact_ids AND tags together: only contacts in both sets qualify."""
    contacts = await _contacts(async_pg_session, 4)
    template = await _template(async_pg_session)

    tag = Tag(id=uuid.uuid4(), name=f"tag_{uuid.uuid4().hex[:8]}")
    async_pg_session.add(tag)
    # Attach tag to contacts 0 and 1 only
    async_pg_session.add(ContactTag(contact_id=contacts[0].id, tag_id=tag.id))
    async_pg_session.add(ContactTag(contact_id=contacts[1].id, tag_id=tag.id))
    await async_pg_session.flush()

    svc = CampaignService(async_pg_session)

    # Select contacts 0, 2, 3 + tag filter → only contact 0 matches both
    campaign = await svc.create_campaign(
        CampaignCreateRequest(
            template_id=template.id,
            name="Intersection",
            type="immediate",
            audience_filter=AudienceFilter(
                contact_ids=[contacts[0].id, contacts[2].id, contacts[3].id],
                tags=[tag.id],
            ),
        ),
        actor_id=None,
    )
    result = await svc.validate_campaign(campaign.id, actor_id=None)
    assert result.ok is True
    assert result.recipient_count == 1


@pytest.mark.asyncio
async def test_get_report_includes_error_breakdown(async_pg_session):
    """get_report should include error_breakdown for campaigns with failed recipients."""
    from app.modules.campaigns.repository import CampaignRecipientRepository

    contacts = await _contacts(async_pg_session, 2)
    template = await _template(async_pg_session)
    svc = CampaignService(async_pg_session)

    campaign = await svc.create_campaign(
        CampaignCreateRequest(template_id=template.id, name="WithFailures", type="immediate"),
        actor_id=None,
    )
    result = await svc.validate_campaign(campaign.id, actor_id=None)
    assert result.ok is True

    # Mark one recipient as failed with a known error, and bump campaign counter
    from app.modules.campaigns.repository import CampaignRepository

    recipient_repo = CampaignRecipientRepository(async_pg_session)
    campaign_repo = CampaignRepository(async_pg_session)
    recipients, _ = await recipient_repo.list_for_campaign(
        campaign.id, page=1, page_size=10
    )
    await recipient_repo.mark_status(
        recipients[0].id, "failed", error="network timeout"
    )
    await campaign_repo.increment_counters(campaign.id, failed_delta=1)
    await async_pg_session.flush()

    report = await svc.get_report(campaign.id)
    assert len(report.error_breakdown) == 1
    assert report.error_breakdown[0].error_message == "network timeout"
    assert report.error_breakdown[0].count == 1
