"""Targeted coverage fill: campaign audience-filter branches, analytics
aggregator + campaign detail, contacts service filters, assignment error
branches."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.auth.models import User
from app.modules.contacts.models import Contact
from app.modules.conversations.models import Conversation
from app.modules.templates.models import Template


def _contact(session, **kw):
    c = Contact(
        id=uuid.uuid4(),
        phone=f"+1888{uuid.uuid4().int % 10_000_000:07d}",
        name="C",
        status=kw.get("status", "active"),
        marketing_opt_out=False,
    )
    session.add(c)
    return c


@pytest.mark.asyncio
async def test_campaign_validate_with_rich_audience_filter(async_pg_session):
    from app.modules.campaigns.schemas import CampaignCreateRequest
    from app.modules.campaigns.service import CampaignService

    for _ in range(2):
        _contact(async_pg_session, status="active")
    _contact(async_pg_session, status="inactive")
    tmpl = Template(
        id=uuid.uuid4(), name=f"t{uuid.uuid4().hex[:6]}", status="approved",
        category="marketing", language="en",
    )
    async_pg_session.add(tmpl)
    await async_pg_session.flush()

    svc = CampaignService(async_pg_session)
    campaign = await svc.create_campaign(
        CampaignCreateRequest(
            template_id=tmpl.id,
            name="Filtered",
            type="immediate",
            audience_filter={
                "status": ["active"],
            },
        ),
        actor_id=None,
    )
    result = await svc.validate_campaign(campaign.id, actor_id=None)
    assert result.ok is True
    assert result.recipient_count == 2


def test_analytics_aggregator_task_runs(committed_db, redis_client):
    from app.modules.analytics.tasks import aggregate_daily_metrics_task

    out = aggregate_daily_metrics_task.run(datetime.now(tz=UTC).date().isoformat())
    assert "target_date" in out


@pytest.mark.asyncio
async def test_analytics_service_campaign_views(async_pg_session):
    from app.modules.analytics.constants import AnalyticsRange
    from app.modules.analytics.service import AnalyticsService

    svc = AnalyticsService(async_pg_session)
    page = await svc.list_campaigns(AnalyticsRange.MONTH, page=1, page_size=10)
    assert page is not None
    # cost/roi already covered via API; exercise the remaining summaries.
    assert await svc.roi(AnalyticsRange.WEEK) is not None


@pytest.mark.asyncio
async def test_contacts_service_filters_and_update(async_pg_session):
    from app.modules.contacts.schemas import (
        ContactListFilters,
        ContactUpdateRequest,
    )
    from app.modules.contacts.service import ContactService

    c = _contact(async_pg_session, status="active")
    await async_pg_session.flush()

    svc = ContactService(async_pg_session)
    items, total = await svc.list_contacts(
        filters=ContactListFilters(status="active"), page=1, page_size=10
    )
    assert total >= 1

    got = await svc.get_contact(c.id)
    assert got.id == c.id

    updated = await svc.update_contact(
        contact_id=c.id, payload=ContactUpdateRequest(name="Updated"),
        actor_id=None,
    )
    assert updated.name == "Updated"


@pytest.mark.asyncio
async def test_assignment_lock_error_branches(async_pg_session):
    from app.core.exceptions import ConversationLockError
    from app.modules.assignments.service import AssignmentService

    agent = User(
        id=uuid.uuid4(), email=f"ag{uuid.uuid4().hex[:6]}@example.com",
        name="A", hashed_password="$2b$12$" + "a" * 53, role="agent",
        is_active=True,
    )
    other = User(
        id=uuid.uuid4(), email=f"ot{uuid.uuid4().hex[:6]}@example.com",
        name="O", hashed_password="$2b$12$" + "a" * 53, role="agent",
        is_active=True,
    )
    async_pg_session.add_all([agent, other])
    contact = _contact(async_pg_session)
    await async_pg_session.flush()
    conv = Conversation(
        id=uuid.uuid4(), contact_id=contact.id, state="AI_ACTIVE",
        ai_enabled=True,
    )
    async_pg_session.add(conv)
    await async_pg_session.flush()

    svc = AssignmentService(async_pg_session)
    await svc.acquire_lock(
        conversation_id=conv.id, agent_id=agent.id, actor_id=agent.id
    )

    # Renew by a different agent → lock error.
    with pytest.raises(ConversationLockError):
        await svc.renew_lock(conversation_id=conv.id, agent_id=other.id)

    # Owner releases successfully.
    await svc.release_lock(
        conversation_id=conv.id, agent_id=agent.id, actor_id=agent.id
    )


@pytest.mark.asyncio
async def test_campaign_audience_filter_all_branches(async_pg_session):
    """Exercise every clause of select_audience_contact_ids: tags,
    status, assigned_agent_id, last-interaction window."""
    import uuid as _uuid
    from datetime import datetime

    from app.modules.campaigns.repository import CampaignRepository
    from app.modules.categorization.models import ContactTag, Tag

    agent = User(
        id=_uuid.uuid4(), email=f"ag{_uuid.uuid4().hex[:6]}@example.com",
        name="A", hashed_password="$2b$12$" + "a" * 53, role="agent",
        is_active=True,
    )
    async_pg_session.add(agent)
    tag = Tag(id=_uuid.uuid4(), name=f"vip-{_uuid.uuid4().hex[:6]}")
    async_pg_session.add(tag)
    await async_pg_session.flush()

    match = Contact(
        id=_uuid.uuid4(), phone="+15551230001", name="Match",
        status="active", marketing_opt_out=False,
        assigned_agent_id=agent.id,
        last_interaction_at=datetime(2026, 5, 10, tzinfo=UTC),
    )
    async_pg_session.add(match)
    await async_pg_session.flush()
    async_pg_session.add(
        ContactTag(contact_id=match.id, tag_id=tag.id)
    )
    await async_pg_session.flush()

    repo = CampaignRepository(async_pg_session)
    ids = await repo.select_audience_contact_ids(
        filter_payload={
            "tags": [str(tag.id)],
            "status": ["active"],
            "assigned_agent_id": str(agent.id),
            "last_interaction_after": "2026-05-01T00:00:00+00:00",
            "last_interaction_before": "2026-05-31T00:00:00+00:00",
        }
    )
    assert match.id in ids


@pytest.mark.asyncio
async def test_campaign_recipient_repo_async_methods(async_pg_session):
    import uuid as _uuid

    from app.modules.campaigns.repository import (
        CampaignRecipientRepository,
        CampaignRepository,
    )

    tmpl = Template(
        id=_uuid.uuid4(), name=f"t{_uuid.uuid4().hex[:6]}", status="approved",
        category="marketing", language="en",
    )
    async_pg_session.add(tmpl)
    contact = _contact(async_pg_session)
    await async_pg_session.flush()

    crepo = CampaignRepository(async_pg_session)
    campaign = await crepo.create(
        template_id=tmpl.id, name="RR", type="immediate", status="draft",
        audience_filter={}, validation_errors=[],
    )
    rrepo = CampaignRecipientRepository(async_pg_session)
    inserted = await rrepo.bulk_insert(
        campaign_id=campaign.id, contact_ids=[contact.id]
    )
    assert inserted == 1

    breakdown = await rrepo.count_by_status(campaign.id)
    assert breakdown.get("pending", 0) == 1

    cancelled = await rrepo.cancel_pending(campaign.id)
    assert cancelled == 1

    await crepo.increment_counters(campaign.id, sent_delta=1)
    refreshed = await crepo.get(campaign.id)
    assert refreshed.sent_count == 1
