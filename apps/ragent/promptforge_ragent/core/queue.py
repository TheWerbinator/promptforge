"""Postgres SKIP LOCKED job queue — ragent's ingest jobs.

ragent enqueues onto the **same `jobs` table apps/api owns** (migration 0004) and
runs a worker that claims rows of `kind="ingest_document"`. apps/api's eval
worker only claims `kind="eval_case"`, so the two consumers coexist on one table
filtered by kind — the one-DB principle the platform already follows. The table
is shared; this client isn't (it's a trimmed copy of api's queue, scoped to what
ingest needs — no batch channel, no SSE fanout). Raw `text()` SQL, no ORM Job
model, so ragent doesn't have to model a table it doesn't migrate.

Claim semantics: a `ClaimedJob` acks on clean exit and requeues-with-backoff (up
to max_attempts, then terminal `failed`) on exception — so a handler that raises a
transient error gets retried for free, while a handler that returns normally is
done.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

INGEST_KIND = "ingest_document"
NOTIFY_CHANNEL = "jobs"


@dataclass
class ClaimedJob:
    """In-flight job. Async context manager: ack on clean exit, fail/requeue on raise."""

    id: int
    kind: str
    payload: dict[str, Any]
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
        return False  # never swallow

    @property
    def is_last_attempt(self) -> bool:
        """True when a further failure would exhaust retries (this is the final try)."""
        return self.attempts >= self.max_attempts


class Queue:
    """Thin client over the shared jobs table: enqueue, claim, ack, fail, consume."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sessions = session_factory

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        run_after: datetime | None = None,
        max_attempts: int = 3,
    ) -> int:
        async with self._sessions() as session:
            job_id = (
                await session.execute(
                    text(
                        "INSERT INTO jobs (kind, payload, run_after, max_attempts) "
                        "VALUES (:kind, CAST(:payload AS jsonb), "
                        "        COALESCE(:run_after, now()), :max_attempts) "
                        "RETURNING id"
                    ),
                    {
                        "kind": kind,
                        "payload": json.dumps(payload),
                        "run_after": run_after,
                        "max_attempts": max_attempts,
                    },
                )
            ).scalar_one()
            # Function form (not the NOTIFY statement) so bound params work.
            await session.execute(
                text("SELECT pg_notify(:channel, :msg)"),
                {"channel": NOTIFY_CHANNEL, "msg": f"job_enqueued:{kind}"},
            )
            await session.commit()
            return int(job_id)

    async def claim(self, kind: str, *, limit: int = 1) -> list[ClaimedJob]:
        """Atomically claim up to `limit` queued rows of `kind`, skipping locked ones."""
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
                            "RETURNING id, kind, payload, attempts, max_attempts"
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
        """Requeue with exponential backoff if attempts remain, else mark terminal."""
        async with self._sessions() as session:
            if job.attempts < job.max_attempts:
                # Compute backoff with the DB clock (now() + interval), not the app
                # host clock, so it's correct even when the container clock drifts
                # ahead of the host (Docker Desktop / WSL2). 2s, 4s, … capped at 60s.
                backoff_secs = min(60, 2**job.attempts)
                await session.execute(
                    text(
                        "UPDATE jobs SET status='queued', claimed_at=NULL, "
                        "                run_after = now() + make_interval(secs => :secs), "
                        "                error=:err WHERE id=:id"
                    ),
                    {"id": job.id, "secs": backoff_secs, "err": error[:1000]},
                )
            else:
                await session.execute(
                    text(
                        "UPDATE jobs SET status='failed', finished_at=now(), "
                        "                error=:err WHERE id=:id"
                    ),
                    {"id": job.id, "err": error[:1000]},
                )
            await session.commit()

    @contextlib.asynccontextmanager
    async def consume(
        self,
        kind: str,
        *,
        batch_size: int = 1,
        poll_interval_ms: int = 250,
    ) -> AsyncIterator[AsyncIterator[ClaimedJob]]:
        """Yield jobs of `kind` as they appear, polling on an interval when idle."""

        async def _stream() -> AsyncIterator[ClaimedJob]:
            while True:
                claimed = await self.claim(kind, limit=batch_size)
                if claimed:
                    for job in claimed:
                        yield job
                    continue
                await asyncio.sleep(poll_interval_ms / 1000)

        yield _stream()
