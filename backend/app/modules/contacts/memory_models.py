"""Client memory model — tracks per-contact memory files stored on the Railway volume.

Each contact can have one memory record. The actual memory content lives as a JSON
file at ``/app/media/memories/{contact_id}.json`` on the Railway volume; the DB row
is an index that tracks version, preview, and interaction count.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.modules.contacts.models import Contact


class ClientMemory(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "client_memories"

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(
        String(512), nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    summary_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_interactions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    contact: Mapped["Contact"] = relationship(
        "Contact", back_populates="memory"
    )
