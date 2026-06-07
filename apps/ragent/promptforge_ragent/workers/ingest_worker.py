"""Ingest worker process.

Runs as a second Fly process alongside the ragent web service (see fly.toml
[processes]). Claims jobs of kind="ingest_document" off the shared Postgres queue
and drives `services.ingest.ingest_document` from each document's stored bytes.

Transient embedding failures (`RetriableEmbeddingError`) are re-raised so the
queue requeues with backoff; on the final attempt the document is marked FAILED
so it doesn't hang in INGESTING forever. Deterministic failures are recorded by
`ingest_document` itself (status FAILED) and the job is acked.

Entry: `python -m promptforge_ragent.workers.ingest_worker`
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from promptforge_ragent.core.db import get_session_factory
from promptforge_ragent.core.queue import INGEST_KIND, ClaimedJob, Queue
from promptforge_ragent.models import Document, DocumentStatus
from promptforge_ragent.services.embeddings import RetriableEmbeddingError
from promptforge_ragent.services.ingest import ingest_document

log = logging.getLogger("promptforge.ragent.worker")

SessionFactory = async_sessionmaker[AsyncSession]


async def enqueue_ingest(queue: Queue, document_id: UUID) -> int:
    """Enqueue an ingest job for a document. Used by the upload + seed paths."""
    return await queue.enqueue(INGEST_KIND, {"document_id": str(document_id)})


async def _handle_ingest(job: ClaimedJob, session_factory: SessionFactory) -> None:
    document_id = UUID(str(job.payload["document_id"]))
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            log.warning("ingest: document %s not found; acking", document_id)
            return
        if document.raw_content is None:
            document.status = DocumentStatus.FAILED
            document.error = "no raw_content to ingest"
            await session.commit()
            return

        try:
            await ingest_document(session, document, document.raw_content)
            await session.commit()
        except RetriableEmbeddingError:
            await session.rollback()
            if job.is_last_attempt:
                # Retries exhausted — record a durable failure and ack the job.
                document = await session.get(Document, document_id)
                if document is not None:
                    document.status = DocumentStatus.FAILED
                    document.error = "embedding failed after retries"
                    await session.commit()
                return
            raise  # requeue with backoff via ClaimedJob.__aexit__


async def _run_one(job: ClaimedJob, session_factory: SessionFactory) -> None:
    # The job context manager records ack (clean exit) or fail/requeue (on raise).
    # A re-raised transient error has already been turned into a requeue by
    # __aexit__, so swallow + log here to keep the consume loop alive.
    try:
        async with job:
            await _handle_ingest(job, session_factory)
    except Exception:
        log.exception("ingest job %s raised (handled by queue ack/requeue)", job.id)


async def _consume_forever(
    queue: Queue, session_factory: SessionFactory, stop: asyncio.Event
) -> None:
    async with queue.consume(INGEST_KIND, batch_size=2) as stream:
        async for job in stream:
            if stop.is_set():
                break
            await _run_one(job, session_factory)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    session_factory = get_session_factory()
    queue = Queue(session_factory)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Windows asyncio loops don't support signal handlers; Ctrl+C still works.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    consumer = asyncio.create_task(_consume_forever(queue, session_factory, stop))
    log.info("ingest_worker started; polling kind=%s", INGEST_KIND)
    await stop.wait()
    log.info("ingest_worker shutting down")
    consumer.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await consumer


if __name__ == "__main__":
    asyncio.run(main())
