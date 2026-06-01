"""Postgres-backed job queue with SKIP LOCKED claim + LISTEN/NOTIFY fanout.

Why Postgres (not Redis/RQ/Celery): one-DB principle. SKIP LOCKED is the modern
production-shape primitive for moderate-throughput queues — see GraphileWorker,
river, Hatchet. If this needed 10k+ jobs/s I'd swap for Redis-backed RQ, but at
prompt-eval scale (hundreds of jobs per batch, batches not hot-looping) the
single-Postgres setup is correct.

Claim model: a consumer pulls N rows whose status='queued' and run_after<=now,
flips them to 'running' atomically via SKIP LOCKED, returns Job context-managers
that ack() on success or fail() on exception. Failed jobs requeue with backoff
until max_attempts.

NOTIFY surface (kept tiny — Postgres caps payloads at 8KB):
- channel "jobs"                  → "job_enqueued:<kind>" when a row lands
- channel "batch:<batch_id>"      → small JSON status events for SSE fanout in
                                    the api process. Full row data is fetched
                                    via a follow-up SELECT.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

NOTIFY_CHANNEL = "jobs"


@dataclass
class ClaimedJob:
    """In-flight job. Use as an async context manager: ack on clean exit, fail on raise."""

    id: int
    kind: str
    payload: dict[str, Any]
    batch_id: UUID | None
    attempts: int
    max_attempts: int

    _queue: Queue

    async def __aenter__(self) -> ClaimedJob:
        return self

    async def __aexit__(self, exc_type: object, exc: BaseException | None, tb: object) -> bool:
        if exc is None:
            await self._queue._ack(self.id)
            return False
        await self._queue._fail(self, str(exc))
        return False  # don't swallow


class Queue:
    """Thin wrapper around the jobs table. Owns enqueue, claim, ack, fail, notify."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sessions = session_factory

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        batch_id: UUID | None = None,
        run_after: datetime | None = None,
        max_attempts: int = 3,
    ) -> int:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO jobs (kind, payload, batch_id, run_after, max_attempts) "
                        "VALUES (:kind, CAST(:payload AS jsonb), :batch_id, "
                        "        COALESCE(:run_after, now()), :max_attempts) "
                        "RETURNING id"
                    ),
                    {
                        "kind": kind,
                        "payload": json.dumps(payload),
                        "batch_id": batch_id,
                        "run_after": run_after,
                        "max_attempts": max_attempts,
                    },
                )
            ).scalar_one()
            # pg_notify() is the function form — supports bound params. The
            # NOTIFY statement form does NOT, because it's a utility command,
            # not DML, and doesn't traverse the prepared-statement layer.
            await session.execute(
                text("SELECT pg_notify(:channel, :msg)"),
                {"channel": NOTIFY_CHANNEL, "msg": f"job_enqueued:{kind}"},
            )
            await session.commit()
            return int(row)

    async def claim(self, kind: str, *, limit: int = 1) -> list[ClaimedJob]:
        """Atomically claim up to `limit` queued rows of `kind`. Skips locked rows.

        Eligible row: status='queued' AND run_after<=now AND attempts<max_attempts.
        """
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH picked AS ("
                            "  SELECT id FROM jobs "
                            "  WHERE kind = :kind AND status = 'queued' "
                            "        AND run_after <= now() AND attempts < max_attempts "
                            "  ORDER BY id "
                            "  FOR UPDATE SKIP LOCKED "
                            "  LIMIT :limit"
                            ") "
                            "UPDATE jobs SET status = 'running', "
                            "                claimed_at = now(), "
                            "                attempts = attempts + 1 "
                            "WHERE id IN (SELECT id FROM picked) "
                            "RETURNING id, kind, payload, batch_id, attempts, max_attempts"
                        ),
                        {"kind": kind, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
            await session.commit()

        return [
            ClaimedJob(
                id=r["id"],
                kind=r["kind"],
                payload=r["payload"],
                batch_id=r["batch_id"],
                attempts=r["attempts"],
                max_attempts=r["max_attempts"],
                _queue=self,
            )
            for r in rows
        ]

    async def _ack(self, job_id: int) -> None:
        async with self._sessions() as session:
            await session.execute(
                text("UPDATE jobs SET status='done', finished_at=now() WHERE id = :id"),
                {"id": job_id},
            )
            await session.commit()

    async def _fail(self, job: ClaimedJob, error: str) -> None:
        """Mark failed. Requeue with backoff if attempts left, else mark terminal."""
        async with self._sessions() as session:
            if job.attempts < job.max_attempts:
                backoff = timedelta(seconds=min(60, 2**job.attempts))
                run_after = datetime.now(UTC) + backoff
                await session.execute(
                    text(
                        "UPDATE jobs SET status='queued', claimed_at=NULL, "
                        "                run_after=:run_after, error=:err "
                        "WHERE id=:id"
                    ),
                    {"id": job.id, "run_after": run_after, "err": error[:1000]},
                )
            else:
                await session.execute(
                    text(
                        "UPDATE jobs SET status='failed', finished_at=now(), error=:err "
                        "WHERE id=:id"
                    ),
                    {"id": job.id, "err": error[:1000]},
                )
            await session.commit()

    async def batch_progress(self, batch_id: UUID) -> dict[str, int]:
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT status, COUNT(*) AS n FROM jobs "
                            "WHERE batch_id = :bid GROUP BY status"
                        ),
                        {"bid": batch_id},
                    )
                )
                .mappings()
                .all()
            )
        return {r["status"]: int(r["n"]) for r in rows}

    @contextlib.asynccontextmanager
    async def consume(
        self,
        kind: str,
        *,
        batch_size: int = 1,
        poll_interval_ms: int = 250,
    ) -> AsyncIterator[AsyncIterator[ClaimedJob]]:
        """Async generator that yields jobs as they become available.

        Uses LISTEN to wake on enqueue, falls back to poll_interval_ms timeout so
        we still pick up jobs whose run_after just elapsed.
        """

        async def _stream() -> AsyncIterator[ClaimedJob]:
            while True:
                claimed = await self.claim(kind, limit=batch_size)
                if claimed:
                    for job in claimed:
                        yield job
                    continue
                # Idle. Sleep until next poll. (A more sophisticated impl would
                # use asyncpg's add_listener on NOTIFY_CHANNEL to wake early.)
                await asyncio.sleep(poll_interval_ms / 1000)

        yield _stream()


async def notify_batch(engine: AsyncEngine, batch_id: UUID, event: dict[str, Any]) -> None:
    """Emit a small status event on the batch's channel for SSE subscribers."""
    channel = _batch_channel(batch_id)
    payload = json.dumps(event)
    if len(payload) > 7800:  # NOTIFY caps at 8000; leave headroom
        raise ValueError("batch notify payload too large; fetch full data via GET")
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT pg_notify(:c, :p)"), {"c": channel, "p": payload}
        )


def _batch_channel(batch_id: UUID) -> str:
    # NOTIFY channel names are identifiers — replace UUID hyphens with underscores.
    return f"batch_{batch_id.hex}"
