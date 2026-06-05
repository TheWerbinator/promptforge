"""Ingest orchestrator: parse → chunk → embed → persist chunks for one document.

`ingest_document` is the unit the ingest worker (Phase 4) drives per job. It
records a *durable* terminal state on the document — READY with chunks, or FAILED
with the error — and does not re-raise, mirroring apps/api's eval-runner: a
deterministic failure (bad PDF, unsupported type) is a real data point, not
something to requeue forever. The vector lands in the column matching the
corpus's embedding dimension (1536 → `embedding_1536`, 384 → `embedding_384`);
the other stays NULL, which is what the partial ivfflat indexes rely on.

# TODO(phase-4): classify transient provider errors (rate limit, 5xx) as
# retriable so the worker requeues them instead of marking the document FAILED.
"""

from __future__ import annotations

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.models import Chunk, Corpus, Document, DocumentStatus
from promptforge_ragent.services.chunking import chunk_text
from promptforge_ragent.services.embeddings import embed_texts
from promptforge_ragent.services.parsing import extract_text

log = structlog.get_logger("promptforge.ragent.ingest")


async def ingest_document(session: AsyncSession, document: Document, data: bytes) -> int:
    """Parse, chunk, embed and persist `data` as the document's chunks.

    Returns the number of chunks written (0 on empty content or failure). The
    caller owns the transaction commit.
    """
    corpus = await session.get(Corpus, document.corpus_id)
    if corpus is None:
        document.status = DocumentStatus.FAILED
        document.error = "corpus not found"
        await session.flush()
        return 0

    document.status = DocumentStatus.INGESTING
    document.error = None
    await session.flush()

    try:
        text = extract_text(document.content_type, data)
        chunks = chunk_text(text)
        vectors = await embed_texts(corpus.embedding_model, [c.text for c in chunks])

        # Re-ingest is idempotent: drop any prior chunks for this document first.
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id))

        column = "embedding_1536" if corpus.embedding_model.dim == 1536 else "embedding_384"
        for chunk, vector in zip(chunks, vectors, strict=True):
            session.add(
                Chunk(
                    document_id=document.id,
                    corpus_id=document.corpus_id,
                    org_id=document.org_id,
                    ordinal=chunk.ordinal,
                    content=chunk.text,
                    token_count=chunk.token_count,
                    **{column: vector},
                )
            )

        document.status = DocumentStatus.READY
        await session.flush()
        log.info("ingested", document_id=str(document.id), chunks=len(chunks))
        return len(chunks)
    except Exception as exc:  # terminal record (see module docstring), not re-raised
        document.status = DocumentStatus.FAILED
        document.error = str(exc)[:2000]
        await session.flush()
        log.warning("ingest_failed", document_id=str(document.id), error=str(exc))
        return 0
