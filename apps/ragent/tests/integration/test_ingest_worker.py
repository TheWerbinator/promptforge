"""Integration: the ingest worker drives ingest_document off the queue.

Covers the queue → claim → handler → ingest chain end-to-end, plus the
transient-vs-terminal retry behavior that the worker layers on top of
ingest_document.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from promptforge_ragent.core.queue import INGEST_KIND, Queue
from promptforge_ragent.models import (
    Chunk,
    Corpus,
    Document,
    DocumentContentType,
    DocumentStatus,
    EmbeddingModel,
)
from promptforge_ragent.services import ingest as ingest_module
from promptforge_ragent.services.embeddings import RetriableEmbeddingError
from promptforge_ragent.workers.ingest_worker import _run_one, enqueue_ingest

pytestmark = pytest.mark.integration


def _patch_embed_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed(model: object, texts: list[str]) -> list[list[float]]:
        return [[0.05] * 1536 for _ in texts]

    monkeypatch.setattr(ingest_module, "embed_texts", fake_embed)


def _patch_embed_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed(model: object, texts: list[str]) -> list[list[float]]:
        raise RetriableEmbeddingError("rate limited")

    monkeypatch.setattr(ingest_module, "embed_texts", fake_embed)


async def _seed_document(factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with factory() as session:
        org_id = uuid4()
        await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
        corpus = Corpus(
            org_id=org_id, slug="docs", name="Docs", embedding_model=EmbeddingModel.OPENAI_3_SMALL
        )
        session.add(corpus)
        await session.flush()
        doc = Document(
            corpus_id=corpus.id,
            org_id=org_id,
            title="readme",
            content_type=DocumentContentType.MARKDOWN,
            byte_size=20,
            raw_content=b"# Title\n\nHello world from PromptForge.",
        )
        session.add(doc)
        await session.flush()
        doc_id = doc.id
        await session.commit()
    return doc_id


async def _get_doc(factory: async_sessionmaker[AsyncSession], doc_id: UUID) -> Document:
    async with factory() as session:
        return (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one()


async def _job_status(factory: async_sessionmaker[AsyncSession], job_id: int) -> str:
    async with factory() as session:
        return (
            await session.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id})
        ).scalar_one()


async def _chunk_count(factory: async_sessionmaker[AsyncSession], doc_id: UUID) -> int:
    async with factory() as session:
        return (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)
            )
        ).scalar_one()


async def test_worker_ingests_a_queued_document(
    committed_db: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embed_ok(monkeypatch)
    doc_id = await _seed_document(committed_db)
    queue = Queue(committed_db)

    job_id = await enqueue_ingest(queue, doc_id)
    claimed = (await queue.claim(INGEST_KIND))[0]
    await _run_one(claimed, committed_db)

    assert (await _get_doc(committed_db, doc_id)).status is DocumentStatus.READY
    assert await _chunk_count(committed_db, doc_id) >= 1
    assert await _job_status(committed_db, job_id) == "done"


async def test_transient_error_requeues_without_failing_document(
    committed_db: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embed_transient(monkeypatch)
    doc_id = await _seed_document(committed_db)
    queue = Queue(committed_db)

    job_id = await queue.enqueue(INGEST_KIND, {"document_id": str(doc_id)}, max_attempts=3)
    claimed = (await queue.claim(INGEST_KIND))[0]
    assert not claimed.is_last_attempt
    await _run_one(claimed, committed_db)

    # Job requeued; document NOT marked failed (it'll retry).
    assert await _job_status(committed_db, job_id) == "queued"
    assert (await _get_doc(committed_db, doc_id)).status is not DocumentStatus.FAILED
    assert await _chunk_count(committed_db, doc_id) == 0


async def test_transient_error_on_last_attempt_marks_failed(
    committed_db: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embed_transient(monkeypatch)
    doc_id = await _seed_document(committed_db)
    queue = Queue(committed_db)

    job_id = await queue.enqueue(INGEST_KIND, {"document_id": str(doc_id)}, max_attempts=1)
    claimed = (await queue.claim(INGEST_KIND))[0]
    assert claimed.is_last_attempt
    await _run_one(claimed, committed_db)

    # Retries exhausted: durable FAILED on the document, job acked done.
    assert (await _get_doc(committed_db, doc_id)).status is DocumentStatus.FAILED
    assert await _job_status(committed_db, job_id) == "done"
