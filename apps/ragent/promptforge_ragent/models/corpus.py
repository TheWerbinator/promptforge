"""Corpus — a named, per-org collection of documents the agent retrieves over.

Each corpus pins one embedding model (`EmbeddingModel`), which decides whether
its chunks populate the 1536-d (OpenAI) or 384-d (local bge) vector column.
Keeping the model on the corpus, not the chunk, is what lets retrieval pick the
right column without inspecting individual rows. See docs/DECISIONS.md
"Why per-corpus embedding model".
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_ragent.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from promptforge_ragent.models.document import Document


class EmbeddingModel(StrEnum):
    # value → vector dimension is fixed: openai = 1536, bge = 384.
    OPENAI_3_SMALL = "openai_text_embedding_3_small"
    BGE_SMALL_EN = "bge_small_en_v1_5"

    @property
    def dim(self) -> int:
        return 1536 if self is EmbeddingModel.OPENAI_3_SMALL else 384


class Corpus(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "corpora"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_corpora_org_slug"),)

    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stable handle used in seed data + URLs (e.g. "promptforge-docs"). Unique per org.
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[EmbeddingModel] = mapped_column(
        SqlEnum(
            EmbeddingModel,
            name="embedding_model",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=EmbeddingModel.OPENAI_3_SMALL,
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="corpus",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Corpus id={self.id} org_id={self.org_id} slug={self.slug!r}>"
