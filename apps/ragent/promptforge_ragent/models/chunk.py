"""Chunk — a retrievable passage with its embedding.

Two nullable vector columns, one per supported embedding model (1536-d OpenAI,
384-d local bge). A chunk's corpus pins exactly one model, so exactly one column
is populated; the other stays NULL. That's why the ivfflat indexes are
*partial* (`WHERE embedding_xxxx IS NOT NULL`) — each index only covers the rows
that actually use that model, instead of indexing a column that's NULL for every
chunk from the other-model corpora. ivfflat with 100 lists is sufficient at demo
scale; the documented switch to hnsw is past ~100k chunks (docs/DECISIONS.md).

BM25 (the lexical half of hybrid retrieval) runs in-process via rank-bm25, so
there's no tsvector column here — only the dense vectors live in Postgres.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_ragent.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from promptforge_ragent.models.document import Document


class Chunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_chunks_document_id_ordinal"),
        # Partial ivfflat indexes — only the rows whose column is non-NULL.
        Index(
            "ix_chunks_embedding_1536_ivfflat",
            "embedding_1536",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding_1536": "vector_cosine_ops"},
            postgresql_where=text("embedding_1536 IS NOT NULL"),
        ),
        Index(
            "ix_chunks_embedding_384_ivfflat",
            "embedding_384",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding_384": "vector_cosine_ops"},
            postgresql_where=text("embedding_384 IS NOT NULL"),
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized so retrieval can scope to a corpus (and a tenant) without
    # joining back through documents on the hot path.
    corpus_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("corpora.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Position of this chunk within its document (0-based).
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    embedding_1536: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_384: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        return f"<Chunk id={self.id} document_id={self.document_id} ordinal={self.ordinal}>"
