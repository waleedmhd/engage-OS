"""Contact Celery tasks."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import structlog
from celery import Task

from app.celery_app import celery_app
from app.modules.contacts.import_csv import (
    MAX_IMPORT_ROWS,
    ParsedContactRow,
    ParseError,
    parse_csv,
)

logger = structlog.get_logger(__name__)

# Contacts with status=contacted and no reply within this window
# are swept to follow_up.
_FOLLOW_UP_SWEEP_HOURS = 12
_FOLLOW_UP_LOCK_TTL = 120  # seconds — prevent overlapping sweeps across workers


@celery_app.task(
    name="contacts.tasks.sweep_follow_up_task",
    bind=True,
    max_retries=1,
    default_retry_delay=120,
)
def sweep_follow_up_task(self: Task) -> int:
    """
    Sweep contacts stuck in 'contacted' with no reply for >12 hours → 'follow_up'.

    Uses a PostgreSQL advisory lock so only one worker runs the sweep at a time.
    Returns the number of contacts transitioned.
    """
    import sqlalchemy as sa

    from app.db.session import sync_session_factory
    from app.modules.contacts.constants import ContactStatus
    from app.modules.contacts.models import Contact

    with sync_session_factory() as session:
        # Advisory lock to serialise sweeps across workers.
        lock_id = 1729  # arbitrary, unique to this task
        acquired = session.execute(
            sa.text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id}
        ).scalar()
        if not acquired:
            logger.info("follow_up_sweep_skipped_lock_held")
            return 0

        try:
            cutoff = datetime.now(tz=UTC) - timedelta(hours=_FOLLOW_UP_SWEEP_HOURS)

            # Find contacts: contacted, past the window, no reply since.
            result = session.execute(
                sa.update(Contact)
                .where(
                    Contact.status == ContactStatus.CONTACTED.value,
                    Contact.last_contacted_at <= cutoff,
                    sa.or_(
                        Contact.last_inbound_at.is_(None),
                        Contact.last_inbound_at < Contact.last_contacted_at,
                    ),
                )
                .values(status=ContactStatus.FOLLOW_UP.value)
            )
            session.commit()
            updated = result.rowcount or 0  # type: ignore[attr-defined]

            if updated:
                logger.info(
                    "follow_up_sweep_completed",
                    transitioned=updated,
                    cutoff_utc=cutoff.isoformat(),
                )
            return updated
        finally:
            session.execute(
                sa.text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id}
            )
            session.commit()


@celery_app.task(
    name="contacts.tasks.import_csv_task",
    bind=True,
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def import_csv_task(self, csv_path: str) -> dict[str, int | list[dict]]:
    """Bulk CSV import via Celery worker (sync session).

    Used for very large imports queued out-of-band. The synchronous HTTP
    endpoint at POST /contacts/import handles interactive admin uploads
    in-process; this task is the offline alternative for files staged on
    disk (e.g. uploaded to a shared volume, S3 sync, etc).

    Returns the same shape as ContactImportReceipt (counts + capped errors)
    so the calling system can poll the Celery result backend and surface
    the same data to the user.

    The task uses the sync ContactRepository (`upsert_by_phone_sync`) so it
    runs inside the worker's synchronous session — async sessions are not
    safe to share across Celery's prefork pool.
    """
    from app.db.session import sync_session_factory
    from app.modules.audit.models import AuditLog
    from app.modules.contacts.repository import ContactRepository

    if not os.path.exists(csv_path):
        logger.error("import_csv_missing_file", path=csv_path)
        raise FileNotFoundError(csv_path)

    with open(csv_path, "rb") as fh:
        raw = fh.read()

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []
    total_rows = 0
    error_cap = 100

    with sync_session_factory() as session:
        repo = ContactRepository(session)  # type: ignore[arg-type]

        for parsed in parse_csv(raw, max_rows=MAX_IMPORT_ROWS):
            total_rows += 1

            if isinstance(parsed, ParseError):
                if parsed.error == "csv_missing_phone_column":
                    return {
                        "total_rows": 0,
                        "created": 0,
                        "updated": 0,
                        "skipped": 0,
                        "errors": [
                            {
                                "row": parsed.row_number,
                                "phone": parsed.phone,
                                "error": parsed.error,
                            }
                        ],
                    }
                skipped += 1
                if len(errors) < error_cap:
                    errors.append(
                        {
                            "row": parsed.row_number,
                            "phone": parsed.phone,
                            "error": parsed.error,
                        }
                    )
                continue

            assert isinstance(parsed, ParsedContactRow)
            try:
                from sqlalchemy import select

                from app.modules.contacts.models import Contact

                existed = session.execute(
                    select(Contact).where(Contact.phone == parsed.phone)
                ).scalar_one_or_none()

                contact = repo.upsert_by_phone_sync(phone=parsed.phone, name=parsed.name)

                # Apply optional overwrites — admin upload is authoritative.
                changed = False
                if parsed.name and contact.name != parsed.name:
                    contact.name = parsed.name
                    changed = True
                if parsed.company and contact.company != parsed.company:
                    contact.company = parsed.company
                    changed = True
                if changed:
                    session.flush()

                if existed is None:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:
                logger.warning(
                    "import_csv_row_failed",
                    row=parsed.row_number,
                    phone=parsed.phone,
                    error=type(exc).__name__,
                )
                skipped += 1
                if len(errors) < error_cap:
                    errors.append(
                        {
                            "row": parsed.row_number,
                            "phone": parsed.phone,
                            "error": f"persist_error:{type(exc).__name__}",
                        }
                    )

        # Single audit row for the whole import (avoid per-row explosion).
        session.add(
            AuditLog(
                actor_type="system",
                actor_id=None,
                action="contact.imported_csv",
                entity_type="contact",
                entity_id=None,
                before_state=None,
                after_state={
                    "source": "celery_task",
                    "path": csv_path,
                    "total_rows": total_rows,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                },
            )
        )
        session.commit()

    logger.info(
        "import_csv_completed",
        path=csv_path,
        total_rows=total_rows,
        created=created,
        updated=updated,
        skipped=skipped,
        error_count=len(errors),
    )

    return {
        "total_rows": total_rows,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
