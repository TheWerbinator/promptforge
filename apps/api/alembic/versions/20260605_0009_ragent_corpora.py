"""ragent corpora: corpora, documents, chunks (pgvector), conversations, messages

These tables are ragent's domain, but apps/api owns the single migration history
for the shared database, so the DDL lives here (hand-authored — alembic
autogenerate can't see ragent's models, and pgvector columns + ivfflat partial
indexes have to be hand-written regardless). The vector columns and their
indexes are emitted as raw SQL so apps/api needs no `pgvector` runtime
dependency — it never queries them.

Revision ID: 20260605_0009
Revises: 20260602_0008
Create Date: 2026-06-05
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260605_0009"
down_revision: str | None = "20260602_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    embedding_model = postgresql.ENUM(
        "openai_text_embedding_3_small",
        "bge_small_en_v1_5",
        name="embedding_model",
    )
    content_type = postgresql.ENUM("markdown", "pdf", "html", "text", name="document_content_type")
    doc_status = postgresql.ENUM("pending", "ingesting", "ready", "failed", name="document_status")
    message_role = postgresql.ENUM("user", "assistant", "tool", "system", name="message_role")

    op.create_table(
        "corpora",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("embedding_model", embedding_model, nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name="fk_corpora_org_id_orgs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_corpora_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_corpora"),
        sa.UniqueConstraint("org_id", "slug", name="uq_corpora_org_slug"),
    )
    op.create_index(op.f("ix_corpora_org_id"), "corpora", ["org_id"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("corpus_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("content_type", content_type, nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("status", doc_status, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["corpus_id"], ["corpora.id"], name="fk_documents_corpus_id_corpora", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name="fk_documents_org_id_orgs", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index(op.f("ix_documents_corpus_id"), "documents", ["corpus_id"])
    op.create_index(op.f("ix_documents_org_id"), "documents", ["org_id"])
    op.create_index(op.f("ix_documents_status"), "documents", ["status"])

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("corpus_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["corpus_id"], ["corpora.id"], name="fk_chunks_corpus_id_corpora", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name="fk_chunks_org_id_orgs", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_chunks_document_id_ordinal"),
    )
    op.create_index(op.f("ix_chunks_document_id"), "chunks", ["document_id"])
    op.create_index(op.f("ix_chunks_corpus_id"), "chunks", ["corpus_id"])
    op.create_index(op.f("ix_chunks_org_id"), "chunks", ["org_id"])

    # Vector columns + partial ivfflat indexes as raw SQL (no pgvector dep in api).
    op.execute("ALTER TABLE chunks ADD COLUMN embedding_1536 vector(1536)")
    op.execute("ALTER TABLE chunks ADD COLUMN embedding_384 vector(384)")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_1536_ivfflat ON chunks "
        "USING ivfflat (embedding_1536 vector_cosine_ops) WITH (lists = 100) "
        "WHERE embedding_1536 IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding_384_ivfflat ON chunks "
        "USING ivfflat (embedding_384 vector_cosine_ops) WITH (lists = 100) "
        "WHERE embedding_384 IS NOT NULL"
    )

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("corpus_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name="fk_conversations_org_id_orgs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["corpus_id"],
            ["corpora.id"],
            name="fk_conversations_corpus_id_corpora",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversations_user_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index(op.f("ix_conversations_org_id"), "conversations", ["org_id"])
    op.create_index(op.f("ix_conversations_corpus_id"), "conversations", ["corpus_id"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name="fk_messages_org_id_orgs", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index(op.f("ix_messages_conversation_id"), "messages", ["conversation_id"])
    op.create_index(op.f("ix_messages_org_id"), "messages", ["org_id"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("corpora")
    for enum_name in (
        "message_role",
        "document_status",
        "document_content_type",
        "embedding_model",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
    # Leave the `vector` extension in place — other objects may rely on it.
