"""Template Celery tasks.

Status sync is on-demand only. DSD §4.7/§6.2 does not require periodic
template polling, so there is intentionally NO beat-schedule entry — the
admin-triggered `POST /templates/{id}/sync` endpoint and this task (which
can be dispatched explicitly, e.g. after a Meta webhook) cover the need.
Adding a global poll would impose continuous Meta API load for no DSD
requirement.
"""

from __future__ import annotations

import uuid

from app.celery_app import celery_app
from app.core.logging import get_logger
from app.db.session import sync_session_factory
from app.integrations.meta.client import MetaWhatsAppClient
from app.modules.templates.constants import map_meta_status
from app.modules.templates.repository import TemplateRepository

logger = get_logger(__name__)


@celery_app.task(name="templates.tasks.sync_template_status_task")
def sync_template_status_task(template_id: str) -> None:
    tmpl_uuid = uuid.UUID(template_id)
    with sync_session_factory() as session:
        template = TemplateRepository.get_sync(session, tmpl_uuid)
        if template is None or not template.meta_template_id:
            logger.info("sync_template_status_skipped", template_id=template_id)
            return
        response = MetaWhatsAppClient().get_message_template(
            meta_template_id=template.meta_template_id
        )
        mapped = map_meta_status(response.get("status"))
        TemplateRepository.update_status_sync(session, tmpl_uuid, mapped.value)
        session.commit()
        logger.info(
            "sync_template_status_done",
            template_id=template_id,
            status=mapped.value,
        )
