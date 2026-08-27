"""Canonicalize existing contacts.phone to the digits-only wa_id form.

Background: Meta's inbound webhook reports the sender as a bare ``wa_id``
(digits only, no ``+``). Contacts created before this change were stored in
mixed formats — manual create kept whatever was typed (``+15551234567``), CSV
import kept the leading ``+`` — so the exact-string lookup in
``ContactRepository.upsert_by_phone`` missed on the customer's first reply and
spawned a name-less duplicate contact (a new chat showing only the number).

The application code now stores/looks up the canonical digits-only form
everywhere. This migration brings existing rows into that form so already-saved
contacts stop spawning duplicates.

Collision safety: ``contacts.phone`` has a UNIQUE constraint. We update a row
ONLY when its canonical form is globally unique across the table — i.e. no
other row (already-canonical or also-needing-normalization) reduces to the same
digits. Rows in a colliding cluster (e.g. a pre-existing ``+1555...`` named
contact alongside a ``1555...`` orphan the bug already created) are left
untouched for manual merge, because silently collapsing them here could lose
data (conversations/messages attached to the orphan). Such clusters are the
finite set of contacts that already received a reply before this fix.

Irreversible data transformation: ``downgrade`` is a no-op (we cannot
reconstruct the original ``+``/formatting that was stripped).
"""
from __future__ import annotations

from alembic import op

revision = "014_canonicalize_contact_phone"
down_revision = "013_message_template_fields"
branch_labels = None
depends_on = None


# Canonical form = strip every non-digit character. Mirrors
# app.modules.contacts.phone.canonicalize_phone exactly.
_CANONICAL = "regexp_replace(phone, '[^0-9]', '', 'g')"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE contacts c
        SET phone = {_CANONICAL.replace('phone', 'c.phone')}
        WHERE c.phone <> {_CANONICAL.replace('phone', 'c.phone')}
          AND (
            SELECT COUNT(*) FROM contacts c2
            WHERE {_CANONICAL.replace('phone', 'c2.phone')}
                  = {_CANONICAL.replace('phone', 'c.phone')}
          ) = 1
        """
    )


def downgrade() -> None:
    # Irreversible: the original formatting/'+' cannot be reconstructed.
    pass
