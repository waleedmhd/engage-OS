"""DocumentStore — abstract file storage for ERP documents.

Phase 1 stores bytea blobs in Postgres (`documents`) so documents are
transactional with their owning entity and covered by existing PITR backups.
Swap to R2/S3 by implementing the same ABC and changing one config key.

Usage:
    from app.core.storage import get_document_store

    store = get_document_store()
    doc = await store.put(b"pdf_bytes", "invoice.pdf", "application/pdf",
                          entity_type="sales_invoice", entity_id=invoice_id)
    content, mime = await store.get(doc.id)
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class StoredDocument:
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    filename: str
    mime_type: str
    sha256: str
    byte_size: int
    created_at: datetime


class DocumentStore(ABC):
    """Abstract interface for document storage."""

    @abstractmethod
    async def put(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
    ) -> StoredDocument: ...

    @abstractmethod
    async def get(self, doc_id: uuid.UUID) -> tuple[bytes, str] | None:
        """Return (bytes, mime_type) or None if not found."""
        ...

    @abstractmethod
    async def delete(self, doc_id: uuid.UUID) -> bool:
        """Delete a document. Returns True if it existed."""
        ...

    @abstractmethod
    async def list_for(
        self, entity_type: str, entity_id: uuid.UUID
    ) -> list[StoredDocument]: ...


class PostgresDocumentStore(DocumentStore):
    """Store documents as BYTEA rows in `documents`."""

    def __init__(self, session_factory) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        self._session_factory: async_sessionmaker = session_factory

    async def put(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
    ) -> StoredDocument:
        from app.core.storage import StoredDocument as SDoc

        sha = hashlib.sha256(data).hexdigest()
        doc_id = uuid.uuid4()
        now = datetime.now(tz=timezone.utc)

        async with self._session_factory() as session:
            from sqlalchemy import text

            await session.execute(
                text(
                    """INSERT INTO documents
                       (id, entity_type, entity_id, filename, mime_type, bytes, sha256, byte_size, created_at)
                       VALUES (:id, :entity_type, :entity_id, :filename, :mime_type,
                               :bytes, :sha256, :byte_size, :created_at)"""
                ),
                {
                    "id": doc_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "filename": filename,
                    "mime_type": mime_type,
                    "bytes": data,
                    "sha256": sha,
                    "byte_size": len(data),
                    "created_at": now,
                },
            )
            await session.commit()

        return SDoc(
            id=doc_id,
            entity_type=entity_type,
            entity_id=entity_id,
            filename=filename,
            mime_type=mime_type,
            sha256=sha,
            byte_size=len(data),
            created_at=now,
        )

    async def get(self, doc_id: uuid.UUID) -> tuple[bytes, str] | None:
        from sqlalchemy import text

        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT bytes, mime_type FROM documents WHERE id = :id"
                ),
                {"id": doc_id},
            )
            row = result.one_or_none()
            if row is None:
                return None
            return row[0], row[1]

    async def delete(self, doc_id: uuid.UUID) -> bool:
        from sqlalchemy import text

        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "DELETE FROM documents WHERE id = :id"
                ),
                {"id": doc_id},
            )
            await session.commit()
            return result.rowcount > 0

    async def list_for(
        self, entity_type: str, entity_id: uuid.UUID
    ) -> list[StoredDocument]:
        from sqlalchemy import text

        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """SELECT id, entity_type, entity_id, filename, mime_type,
                              sha256, byte_size, created_at
                       FROM documents
                       WHERE entity_type = :entity_type AND entity_id = :entity_id
                       ORDER BY created_at DESC"""
                ),
                {"entity_type": entity_type, "entity_id": entity_id},
            )
            return [
                StoredDocument(
                    id=row[0],
                    entity_type=row[1],
                    entity_id=row[2],
                    filename=row[3],
                    mime_type=row[4],
                    sha256=row[5],
                    byte_size=row[6],
                    created_at=row[7],
                )
                for row in result
            ]


# ------------------------------------------------------------------ factory

_store: DocumentStore | None = None


def get_document_store() -> DocumentStore:
    """Return the configured DocumentStore singleton.

    Reads `ERP_DOCUMENT_STORE` from settings — currently only "postgres" is
    implemented. Future: "r2" / "s3".
    """
    global _store
    if _store is not None:
        return _store

    from app.core.config import get_settings
    from app.db.session import async_session_factory

    _store = PostgresDocumentStore(async_session_factory)
    return _store


def _reset_document_store() -> None:
    """Clear the cached store — test helper."""
    global _store
    _store = None
