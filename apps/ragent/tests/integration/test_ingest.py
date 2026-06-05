"""Integration: ingest_document end-to-end against real Postgres (litellm mocked).

Drives the full parse → chunk → embed → persist path and asserts the durable
outcomes: chunks land with a 1536-d vector in the right column, the document goes
READY, re-ingest is idempotent, and a parse failure records FAILED + error.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.models import (
    Chunk,
    Corpus,
    Document,
    DocumentContentType,
    DocumentStatus,
    EmbeddingModel,
)
from promptforge_ragent.services import embeddings
from promptforge_ragent.services.ingest import ingest_document

pytestmark = pytest.mark.integration


def _mock_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    # embeddings._embed_openai reads get_settings() for the key; give it the
    # minimal env so Settings loads (the litellm call itself is mocked below).
    monkeypatch.setenv("PF_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()

    async def fake_aembedding(**kwargs: object) -> SimpleNamespace:
        texts = kwargs["input"]
        assert isinstance(texts, list)
        return SimpleNamespace(data=[{"embedding": [0.05] * 1536} for _ in texts])

    monkeypatch.setattr(embeddings.litellm, "aembedding", fake_aembedding)


async def _seed_corpus(session: AsyncSession, model: EmbeddingModel) -> Document:
    org_id = uuid4()
    await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
    corpus = Corpus(org_id=org_id, slug="docs", name="Docs", embedding_model=model)
    session.add(corpus)
    await session.flush()
    doc = Document(
        corpus_id=corpus.id,
        org_id=org_id,
        title="readme",
        content_type=DocumentContentType.MARKDOWN,
        byte_size=42,
    )
    session.add(doc)
    await session.flush()
    return doc


async def _chunk_count(session: AsyncSession, doc_id: object) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)
        )
    ).scalar_one()


async def test_ingest_persists_chunks_with_vectors(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_openai(monkeypatch)
    doc = await _seed_corpus(db_session, EmbeddingModel.OPENAI_3_SMALL)

    written = await ingest_document(db_session, doc, b"# Title\n\nHello world from PromptForge.")
    assert written >= 1
    assert doc.status is DocumentStatus.READY
    assert doc.error is None

    chunk = (
        (await db_session.execute(select(Chunk).where(Chunk.document_id == doc.id)))
        .scalars()
        .first()
    )
    assert chunk is not None
    assert len(chunk.embedding_1536) == 1536
    assert chunk.embedding_384 is None
    assert chunk.org_id == doc.org_id
    assert chunk.corpus_id == doc.corpus_id


async def test_reingest_is_idempotent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_openai(monkeypatch)
    doc = await _seed_corpus(db_session, EmbeddingModel.OPENAI_3_SMALL)

    first = await ingest_document(db_session, doc, b"alpha beta gamma")
    after_first = await _chunk_count(db_session, doc.id)
    second = await ingest_document(db_session, doc, b"alpha beta gamma")
    after_second = await _chunk_count(db_session, doc.id)

    assert first == second
    assert after_first == after_second  # old chunks replaced, not duplicated


async def test_parse_failure_records_failed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_openai(monkeypatch)
    doc = await _seed_corpus(db_session, EmbeddingModel.OPENAI_3_SMALL)
    doc.content_type = DocumentContentType.PDF
    await db_session.flush()

    written = await ingest_document(db_session, doc, b"not a real pdf")
    assert written == 0
    assert doc.status is DocumentStatus.FAILED
    assert doc.error
    assert await _chunk_count(db_session, doc.id) == 0
