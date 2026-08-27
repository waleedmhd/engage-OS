"""MediaAsset model — persisted media files (images, video, audio, documents)."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, LargeBinary, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.media.constants import MediaType

if TYPE_CHECKING:
    from app.modules.messaging.models import Message


class MediaAsset(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        enum_check("media_type", MediaType, "ck_media_assets_type_valid"),
    )

    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_data: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))
    duration_seconds: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    meta_media_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    message: Mapped["Message"] = relationship(
        "Message", back_populates="media"
    )
