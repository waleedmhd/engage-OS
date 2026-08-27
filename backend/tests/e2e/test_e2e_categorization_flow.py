"""E2E: AI tag-suggestion sync-ingest path + concurrency invariant.

Exercises `CategorizationService.create_suggestion_sync` end-to-end against
real Postgres, then verifies invariant #14: concurrent suggestions for the
same tag name produce exactly one Tag row (pg_insert ON CONFLICT DO NOTHING).

Approve/reject HTTP flow is covered by the categorization router/service
unit tiers; this file focuses on the sync ingest contract the AI decision
engine actually calls.
"""
from __future__ import annotations

import threading

from tests.factories import make_contact, make_conversation, make_user


def test_categorization_sync_ingest_creates_pending_suggestion(pg_session, redis_client):
    from app.modules.categorization.models import Tag, TagSuggestion
    from app.modules.categorization.service import CategorizationService

    make_user(pg_session, role="admin")
    contact = make_contact(pg_session)
    make_conversation(pg_session, contact=contact)
    pg_session.commit()

    suggestion = CategorizationService.create_suggestion_sync(
        pg_session,
        contact_id=contact.id,
        tag_name="buyer-lead",
        confidence=0.91,
        reason="ai_intent",
    )
    pg_session.commit()
    assert suggestion is not None

    pg_session.expire_all()
    pending = pg_session.query(TagSuggestion).filter_by(id=suggestion.id).one()
    assert pending.status in ("pending", "PENDING")
    assert pending.contact_id == contact.id

    tags = pg_session.query(Tag).filter_by(name="buyer-lead").all()
    assert len(tags) == 1


def test_concurrent_same_tag_yields_single_row(pg_engine):
    """Invariant #14: two threads creating the same tag concurrently must end
    up with exactly one row (pg_insert(...).on_conflict_do_nothing on
    Tag.name)."""
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from app.modules.categorization.models import Tag
    from app.modules.categorization.service import CategorizationService

    Factory = sessionmaker(
        pg_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )

    with Factory() as setup:
        contact = make_contact(setup)
        make_conversation(setup, contact=contact)
        setup.commit()
        contact_id = contact.id

    results: list = [None, None]

    def worker(idx):
        with Factory() as s:
            suggestion = CategorizationService.create_suggestion_sync(
                s,
                contact_id=contact_id,
                tag_name="race-tag",
                confidence=0.5,
                reason="ai",
            )
            s.commit()
            results[idx] = suggestion.id

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    with Factory() as check:
        tags = check.query(Tag).filter_by(name="race-tag").all()
        assert len(tags) == 1, (
            f"Expected single Tag row under race, found {len(tags)}"
        )

    # Cleanup (these rows leak past the outer fixture's SAVEPOINT because we
    # used the engine directly).
    with Factory() as cleanup:
        cleanup.execute(
            text(
                "DELETE FROM tag_suggestions WHERE contact_id = :c"
            ),
            {"c": contact_id},
        )
        cleanup.execute(text("DELETE FROM tags WHERE name = 'race-tag'"))
        cleanup.execute(
            text("DELETE FROM conversations WHERE contact_id = :c"),
            {"c": contact_id},
        )
        cleanup.execute(
            text("DELETE FROM contacts WHERE id = :c"), {"c": contact_id}
        )
        cleanup.commit()
