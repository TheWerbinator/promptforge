"""Integration: the ragent schema round-trips against real Postgres + pgvector.

Covers the parts that can only be checked against a live DB: the pgvector column
stores and returns a 1536-d vector, cosine-distance ordering works (so the
ivfflat index has something to accelerate), and the corpus→document→chunk and
conversation→message graphs persist with their FKs intact.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.models import (
    Chunk,
    Conversation,
    Corpus,
    Document,
    DocumentStatus,
    EmbeddingModel,
    Message,
    MessageRole,
)

pytestmark = pytest.mark.integration


async def _seed_org_user(session: AsyncSession) -> tuple[object, object]:
    org_id, user_id = uuid4(), uuid4()
    await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
    await session.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": user_id})
    return org_id, user_id


async def test_corpus_document_chunk_roundtrip(db_session: AsyncSession) -> None:
    org_id, user_id = await _seed_org_user(db_session)

    corpus = Corpus(
        org_id=org_id,
        slug="promptforge-docs",
        name="PromptForge Docs",
        embedding_model=EmbeddingModel.OPENAI_3_SMALL,
        created_by=user_id,
    )
    db_session.add(corpus)
    await db_session.flush()

    doc = Document(
        corpus_id=corpus.id,
        org_id=org_id,
        title="README",
        status=DocumentStatus.READY,
        byte_size=1234,
    )
    db_session.add(doc)
    await db_session.flush()

    near = [1.0] + [0.0] * 1535
    far = [0.0] * 1535 + [1.0]
    db_session.add_all(
        [
            Chunk(
                document_id=doc.id,
                corpus_id=corpus.id,
                org_id=org_id,
                ordinal=0,
                content="near chunk",
                embedding_1536=near,
            ),
            Chunk(
                document_id=doc.id,
                corpus_id=corpus.id,
                org_id=org_id,
                ordinal=1,
                content="far chunk",
                embedding_1536=far,
            ),
        ]
    )
    await db_session.flush()

    # Vector round-trips with full dimensionality.
    stored = (await db_session.execute(select(Chunk).where(Chunk.ordinal == 0))).scalar_one()
    assert len(stored.embedding_1536) == 1536
    assert stored.embedding_384 is None

    # Cosine-distance ordering: querying near [1, 0, 0, ...] returns "near" first.
    query = [1.0] + [0.0] * 1535
    ordered = (
        (
            await db_session.execute(
                select(Chunk.content).order_by(Chunk.embedding_1536.cosine_distance(query))
            )
        )
        .scalars()
        .all()
    )
    assert ordered[0] == "near chunk"


async def test_conversation_message_graph(db_session: AsyncSession) -> None:
    org_id, user_id = await _seed_org_user(db_session)

    convo = Conversation(org_id=org_id, user_id=user_id, title="What is PromptForge?")
    db_session.add(convo)
    await db_session.flush()

    db_session.add_all(
        [
            Message(
                conversation_id=convo.id,
                org_id=org_id,
                role=MessageRole.USER,
                content="What is PromptForge?",
            ),
            Message(
                conversation_id=convo.id,
                org_id=org_id,
                role=MessageRole.ASSISTANT,
                content="A prompt-management + eval platform.",
                citations=[{"chunk_id": str(uuid4()), "score": 0.91}],
                tool_calls=[{"tool": "search_docs", "args": {"q": "what is"}}],
            ),
        ]
    )
    await db_session.flush()

    # Query messages directly (ordered) rather than through the lazy relationship.
    rows = (
        (
            await db_session.execute(
                select(Message)
                .where(Message.conversation_id == convo.id)
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [m.role for m in rows] == [MessageRole.USER, MessageRole.ASSISTANT]
    assistant = rows[1]
    assert assistant.citations[0]["score"] == 0.91
    assert assistant.tool_calls[0]["tool"] == "search_docs"
