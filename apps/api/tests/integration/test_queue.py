"""Integration tests for core/queue.py against real Postgres.

The queue is fundamentally a SQL contract — mocking it would test the mock, not
the SKIP LOCKED semantics or NOTIFY delivery. All tests here drive a real
asyncpg engine.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from promptforge_api.core.queue import Queue

pytestmark = pytest.mark.integration


@pytest.fixture
async def queue(pg_url: str, _migrated_engine: None) -> Queue:
    engine = create_async_engine(pg_url, future=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    # Clean jobs between tests so claim/ack counts are deterministic.
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE jobs RESTART IDENTITY"))
    return Queue(factory)


async def test_enqueue_then_claim_returns_job(queue: Queue) -> None:
    job_id = await queue.enqueue("eval_case", {"version_id": "v1", "case_id": "c1"})
    assert job_id > 0

    claimed = await queue.claim("eval_case", limit=5)
    assert len(claimed) == 1
    assert claimed[0].id == job_id
    assert claimed[0].payload == {"version_id": "v1", "case_id": "c1"}
    assert claimed[0].attempts == 1


async def test_claim_filters_by_kind(queue: Queue) -> None:
    await queue.enqueue("eval_case", {})
    await queue.enqueue("ingest_doc", {})
    eval_jobs = await queue.claim("eval_case", limit=10)
    ingest_jobs = await queue.claim("ingest_doc", limit=10)
    assert len(eval_jobs) == 1
    assert len(ingest_jobs) == 1
    assert eval_jobs[0].kind == "eval_case"
    assert ingest_jobs[0].kind == "ingest_doc"


async def test_claim_respects_run_after(queue: Queue) -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    await queue.enqueue("eval_case", {}, run_after=future)
    assert await queue.claim("eval_case", limit=5) == []


async def test_ack_marks_done(queue: Queue, pg_url: str) -> None:
    job_id = await queue.enqueue("eval_case", {})
    [job] = await queue.claim("eval_case")
    async with job:
        pass  # context exit acks
    status = await _status_of(pg_url, job_id)
    assert status == "done"


async def test_fail_with_attempts_left_requeues(queue: Queue, pg_url: str) -> None:
    job_id = await queue.enqueue("eval_case", {}, max_attempts=3)
    [job] = await queue.claim("eval_case")
    with pytest.raises(RuntimeError, match="oops"):
        async with job:
            raise RuntimeError("oops")
    status = await _status_of(pg_url, job_id)
    assert status == "queued"


async def test_fail_after_max_attempts_marks_failed(queue: Queue, pg_url: str) -> None:
    job_id = await queue.enqueue("eval_case", {}, max_attempts=1)
    [job] = await queue.claim("eval_case")
    with pytest.raises(RuntimeError):
        async with job:
            raise RuntimeError("terminal")
    status = await _status_of(pg_url, job_id)
    assert status == "failed"


async def test_skip_locked_two_consumers_no_double_claim(queue: Queue) -> None:
    """Two concurrent claims on the same kind must not return overlapping rows."""
    for _ in range(10):
        await queue.enqueue("eval_case", {})

    a, b = await asyncio.gather(
        queue.claim("eval_case", limit=5),
        queue.claim("eval_case", limit=5),
    )
    a_ids = {j.id for j in a}
    b_ids = {j.id for j in b}
    assert a_ids.isdisjoint(b_ids), f"double-claim! {a_ids & b_ids}"
    assert len(a_ids) + len(b_ids) == 10


async def test_batch_progress_groups_by_status(queue: Queue) -> None:
    batch = uuid4()
    a = await queue.enqueue("eval_case", {}, batch_id=batch)
    b = await queue.enqueue("eval_case", {}, batch_id=batch)
    await queue.enqueue("eval_case", {}, batch_id=batch)

    [job_a] = await queue.claim("eval_case", limit=1)
    async with job_a:
        pass  # ack a

    [job_b] = await queue.claim("eval_case", limit=1)
    with pytest.raises(RuntimeError):
        async with job_b:
            raise RuntimeError("x")
    # b is now requeued (attempts left)

    assert a > 0
    assert b > 0
    progress = await queue.batch_progress(batch)
    # 1 done (a), 2 queued (b requeued, c untouched)
    assert progress.get("done", 0) == 1
    assert progress.get("queued", 0) == 2


async def _status_of(pg_url: str, job_id: int) -> str:
    engine = create_async_engine(pg_url, future=True)
    try:
        async with engine.connect() as conn:
            row = await conn.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id})
            return str(row.scalar_one())
    finally:
        await engine.dispose()
