"""Integration: the shared-jobs-table queue client (claim/ack/requeue/SKIP LOCKED)."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from promptforge_ragent.core.queue import INGEST_KIND, ClaimedJob, Queue

pytestmark = pytest.mark.integration


async def _job_row(factory: async_sessionmaker[AsyncSession], job_id: int) -> dict[str, object]:
    async with factory() as session:
        row = (
            (
                await session.execute(
                    text("SELECT status, attempts, run_after FROM jobs WHERE id = :id"),
                    {"id": job_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def test_enqueue_claim_ack(committed_db: async_sessionmaker[AsyncSession]) -> None:
    queue = Queue(committed_db)
    job_id = await queue.enqueue(INGEST_KIND, {"document_id": "abc"})

    claimed = await queue.claim(INGEST_KIND)
    assert len(claimed) == 1
    assert claimed[0].id == job_id
    assert claimed[0].payload == {"document_id": "abc"}

    async with claimed[0]:  # clean exit → ack
        pass
    assert (await _job_row(committed_db, job_id))["status"] == "done"
    # Nothing left to claim.
    assert await queue.claim(INGEST_KIND) == []


async def test_failure_requeues_with_backoff(
    committed_db: async_sessionmaker[AsyncSession],
) -> None:
    queue = Queue(committed_db)
    job_id = await queue.enqueue(INGEST_KIND, {"x": 1}, max_attempts=3)

    claimed = (await queue.claim(INGEST_KIND))[0]
    with pytest.raises(RuntimeError, match="boom"):
        async with claimed:
            raise RuntimeError("boom")

    row = await _job_row(committed_db, job_id)
    assert row["status"] == "queued"  # requeued, not failed
    assert row["attempts"] == 1
    # Backoff pushed run_after into the future, so it isn't immediately claimable.
    assert await queue.claim(INGEST_KIND) == []


async def test_terminal_fail_after_max_attempts(
    committed_db: async_sessionmaker[AsyncSession],
) -> None:
    queue = Queue(committed_db)
    job_id = await queue.enqueue(INGEST_KIND, {"x": 1}, max_attempts=1)

    claimed = (await queue.claim(INGEST_KIND))[0]
    assert claimed.is_last_attempt
    with pytest.raises(RuntimeError):
        async with claimed:
            raise RuntimeError("nope")

    assert (await _job_row(committed_db, job_id))["status"] == "failed"


async def test_skip_locked_no_double_claim(
    committed_db: async_sessionmaker[AsyncSession],
) -> None:
    queue = Queue(committed_db)
    await queue.enqueue(INGEST_KIND, {"x": 1})

    # Two claimers race for one job; SKIP LOCKED means exactly one wins.
    a, b = await asyncio.gather(queue.claim(INGEST_KIND), queue.claim(INGEST_KIND))
    claimed: list[ClaimedJob] = [*a, *b]
    assert len(claimed) == 1
