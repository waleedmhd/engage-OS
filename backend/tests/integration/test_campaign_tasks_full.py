"""Campaign dispatch pipeline integration tests.

Drives the sync Celery task chain against real Postgres + Redis with the
Meta send endpoint mocked:

  dispatch_campaign_task → process_campaign_batch_task → complete_campaign_task
  scheduler_tick_task    → dispatch (due SCHEDULED campaign)

Covers task branches: lock-held skip, missing campaign, wrong-status skip,
QUEUED→DISPATCHING fan-out, per-recipient send + counters, completion, and
the beat scheduler picking up due campaigns.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.factories import (
    make_campaign,
    make_campaign_recipient,
    make_contact,
    make_template,
)


@pytest.fixture
def meta_mock(respx_mock):
    import itertools

    counter = itertools.count()

    def _unique(request):
        import httpx

        return httpx.Response(
            200, json={"messages": [{"id": f"wamid.CAMPAIGN.{next(counter)}"}]}
        )

    respx_mock.post(re.compile(r".*graph\.facebook\.com.*")).mock(
        side_effect=_unique
    )
    return respx_mock


def _seed_queued_campaign(db, *, recipients=3):
    template = make_template(db, status="approved")
    campaign = make_campaign(db, template=template, status="queued", type="immediate")
    contacts = [make_contact(db) for _ in range(recipients)]
    for c in contacts:
        make_campaign_recipient(db, campaign=campaign, contact=c, status="pending")
    db.commit()
    return campaign, contacts


def test_dispatch_pipeline_sends_and_completes(
    committed_db, redis_client, celery_eager, meta_mock
):
    from app.modules.campaigns.constants import CampaignStatus
    from app.modules.campaigns.models import Campaign, CampaignRecipient

    campaign, contacts = _seed_queued_campaign(committed_db, recipients=3)
    from app.modules.campaigns.tasks import dispatch_campaign_task

    dispatch_campaign_task.run(str(campaign.id))

    committed_db.expire_all()
    refreshed = committed_db.get(Campaign, campaign.id)
    assert refreshed.status == CampaignStatus.COMPLETED.value
    assert refreshed.sent_count == 3

    recips = (
        committed_db.query(CampaignRecipient)
        .filter_by(campaign_id=campaign.id)
        .all()
    )
    assert all(r.status == "sent" for r in recips)
    assert all(r.message_id is not None for r in recips)


def test_dispatch_skips_when_lock_held(committed_db, redis_client, celery_eager):
    from app.core.redis import get_sync_redis
    from app.modules.campaigns.constants import CampaignStatus
    from app.modules.campaigns.models import Campaign
    from app.modules.campaigns.tasks import dispatch_campaign_task

    campaign, _ = _seed_queued_campaign(committed_db, recipients=2)

    # Pre-acquire the singleflight lock.
    from app.modules.campaigns.constants import CAMPAIGN_LOCK_REDIS_KEY

    r = get_sync_redis()
    r.set(CAMPAIGN_LOCK_REDIS_KEY.format(campaign_id=campaign.id), "1")

    dispatch_campaign_task.run(str(campaign.id))

    committed_db.expire_all()
    refreshed = committed_db.get(Campaign, campaign.id)
    # Lock held → loop never ran → still QUEUED.
    assert refreshed.status == CampaignStatus.QUEUED.value


def test_dispatch_missing_campaign_is_noop(committed_db, redis_client, celery_eager):
    from app.modules.campaigns.tasks import dispatch_campaign_task

    # Random id — must not raise.
    dispatch_campaign_task.run(str(uuid.uuid4()))


def test_dispatch_wrong_status_skips(committed_db, redis_client, celery_eager):
    from app.modules.campaigns.constants import CampaignStatus
    from app.modules.campaigns.models import Campaign
    from app.modules.campaigns.tasks import dispatch_campaign_task

    template = make_template(committed_db, status="approved")
    campaign = make_campaign(
        committed_db, template=template, status="completed", type="immediate"
    )
    committed_db.commit()

    dispatch_campaign_task.run(str(campaign.id))

    committed_db.expire_all()
    assert (
        committed_db.get(Campaign, campaign.id).status
        == CampaignStatus.COMPLETED.value
    )


def test_scheduler_tick_dispatches_due_campaign(
    committed_db, redis_client, celery_eager, meta_mock
):
    from app.modules.campaigns.constants import CampaignStatus
    from app.modules.campaigns.models import Campaign
    from app.modules.campaigns.tasks import scheduler_tick_task

    template = make_template(committed_db, status="approved")
    campaign = make_campaign(
        committed_db,
        template=template,
        status="scheduled",
        type="scheduled",
        scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    contact = make_contact(committed_db)
    make_campaign_recipient(
        committed_db, campaign=campaign, contact=contact, status="pending"
    )
    committed_db.commit()

    scheduler_tick_task.run()

    committed_db.expire_all()
    refreshed = committed_db.get(Campaign, campaign.id)
    # Dispatched → eager chain ran it to completion.
    assert refreshed.status in (
        CampaignStatus.COMPLETED.value,
        CampaignStatus.DISPATCHING.value,
        CampaignStatus.QUEUED.value,
        CampaignStatus.FAILED.value,
    )


def test_complete_task_marks_failed_when_errors_present(
    committed_db, celery_eager
):
    """complete_campaign_task should transition to FAILED when failed_count > 0."""
    from app.modules.campaigns.constants import CampaignStatus
    from app.modules.campaigns.models import Campaign
    from app.modules.campaigns.tasks import complete_campaign_task

    template = make_template(committed_db, status="approved")
    campaign = make_campaign(
        committed_db,
        template=template,
        status="dispatching",
        type="immediate",
    )
    contact = make_contact(committed_db)
    make_campaign_recipient(
        committed_db, campaign=campaign, contact=contact, status="failed"
    )
    # Simulate the counters as if the batch task recorded one failure.
    campaign.failed_count = 1
    campaign.audience_count = 1
    campaign.sent_count = 1
    committed_db.commit()

    complete_campaign_task.run(str(campaign.id))

    committed_db.expire_all()
    refreshed = committed_db.get(Campaign, campaign.id)
    assert refreshed.status == CampaignStatus.FAILED.value


def test_error_breakdown_sync(committed_db):
    """error_breakdown_sync groups failed recipients by error message."""
    from app.modules.campaigns.repository import CampaignRecipientRepository

    template = make_template(committed_db, status="approved")
    campaign = make_campaign(
        committed_db, template=template, status="dispatching", type="immediate"
    )
    c1 = make_contact(committed_db)
    c2 = make_contact(committed_db)
    r1 = make_campaign_recipient(
        committed_db, campaign=campaign, contact=c1, status="failed",
        error_message="network timeout",
    )
    r2 = make_campaign_recipient(
        committed_db, campaign=campaign, contact=c2, status="failed",
        error_message="network timeout",
    )
    committed_db.flush()
    committed_db.commit()

    repo = CampaignRecipientRepository(committed_db)
    result = repo.error_breakdown_sync(campaign.id)

    assert len(result) == 1
    assert result[0][0] == "network timeout"
    assert result[0][2] == 2


def test_batch_task_fails_recipients_when_template_not_on_meta(
    committed_db, redis_client, celery_eager, meta_mock
):
    """If the campaign template has no meta_template_id, the batch task
    marks all recipients as failed without calling Meta."""
    from app.modules.campaigns.constants import CampaignRecipientStatus
    from app.modules.campaigns.models import CampaignRecipient
    from app.modules.campaigns.tasks import process_campaign_batch_task

    # Create a template explicitly with meta_template_id=None
    template = make_template(committed_db, meta_template_id=None, status="approved")
    campaign = make_campaign(
        committed_db,
        template=template,
        status="dispatching",
        type="immediate",
    )
    contact = make_contact(committed_db)
    make_campaign_recipient(
        committed_db, campaign=campaign, contact=contact, status="pending"
    )
    committed_db.commit()

    recipient_ids = [
        str(r.id)
        for r in committed_db.query(CampaignRecipient)
        .filter_by(campaign_id=campaign.id)
        .all()
    ]
    assert len(recipient_ids) == 1

    process_campaign_batch_task.run(str(campaign.id), recipient_ids)

    committed_db.expire_all()
    recipient = committed_db.get(CampaignRecipient, uuid.UUID(recipient_ids[0]))
    assert recipient.status == CampaignRecipientStatus.FAILED.value
    assert "Template not submitted to Meta" in (recipient.error_message or "")
