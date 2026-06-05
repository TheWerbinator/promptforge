"""Document — one source file inside a corpus, plus its ingest lifecycle.

`org_id` is denormalized off the parent corpus so a tenant-scoped repository can
filter documents (and below, chunks) without a join back up to corpora — the
same read-perf tradeoff apps/api makes on `Run.org_id`. `status`/`error` carry
the ingest pipeline state (Phase 3+): a document is queued, embedded, then ready
or failed-with-reason.
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_ragent.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from promptforge_ragent.models.chunk import Chunk
    from promptforge_ragent.models.corpus import Corpus


class DocumentContentType(StrEnum):
    MARKDOWN = "markdown"
    PDF = "pdf"
    HTML = "html"
    TEXT = "text"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    corpus_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("corpora.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized from corpus for direct tenant scoping (see module docstring).
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    # Original path/URL the document came from; null for pasted/uploaded blobs.
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[DocumentContentType] = mapped_column(
        SqlEnum(
            DocumentContentType,
            name="document_content_type",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DocumentContentType.MARKDOWN,
    )
    # Raw byte size of the source, enforced against the per-file upload cap.
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[DocumentStatus] = mapped_column(
        SqlEnum(
            DocumentStatus,
            name="document_status",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DocumentStatus.PENDING,
        index=True,
    )
    # Populated when status=failed (parse error, embedding failure, etc.).
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    corpus: Mapped["Corpus"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} corpus_id={self.corpus_id} status={self.status}>"
