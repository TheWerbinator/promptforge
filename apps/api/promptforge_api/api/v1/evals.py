"""Eval suite + case CRUD, batch run, batch detail, and SSE progress stream.

Flow:
  POST   /api/v1/eval-suites                        create a suite
  POST   /api/v1/eval-suites/{id}/cases             add a case
  POST   /api/v1/eval-suites/{id}/run               kick off a batch across versions
  GET    /api/v1/eval-batches/{id}                  batch detail w/ results
  GET    /api/v1/eval-batches/{id}/stream           SSE: live result events

Batch run enqueues one Job per (version_id, case) onto kind="eval_case". The
worker picks them up; each one calls services.eval_runner.run_eval_case which
emits a pg_notify on the batch's channel. The SSE endpoint LISTENs and forwards.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from promptforge_api.core.db import get_engine, get_session, get_session_factory
from promptforge_api.core.deps import Principal, get_principal, get_repo
from promptforge_api.core.queue import Queue, _batch_channel
from promptforge_api.models import (
    EvalBatch,
    EvalCase,
    EvalResult,
    EvalSuite,
    PromptVersion,
)
from promptforge_api.repositories import TenantRepository
from promptforge_api.schemas.eval import (
    EvalBatchDetailResponse,
    EvalBatchResponse,
    EvalBatchRunRequest,
    EvalCaseCreate,
    EvalCaseResponse,
    EvalResultResponse,
    EvalSuiteCreate,
    EvalSuiteResponse,
)

suites_router = APIRouter(prefix="/eval-suites", tags=["evals"])
batches_router = APIRouter(prefix="/eval-batches", tags=["evals"])


@suites_router.post(
    "",
    response_model=EvalSuiteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_suite(
    body: EvalSuiteCreate,
    principal: Principal = Depends(get_principal),
    repo: TenantRepository[EvalSuite] = Depends(get_repo(EvalSuite)),
) -> EvalSuiteResponse:
    try:
        suite = await repo.add(
            name=body.name,
            description=body.description,
            judge_default=body.judge_default,
            created_by=principal.user_id,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="suite name already used in this org",
        ) from exc
    return EvalSuiteResponse.model_validate(suite)


@suites_router.get("", response_model=list[EvalSuiteResponse])
async def list_suites(
    repo: TenantRepository[EvalSuite] = Depends(get_repo(EvalSuite)),
) -> list[EvalSuiteResponse]:
    rows = await repo.list(limit=200, order_by=EvalSuite.created_at.desc())
    return [EvalSuiteResponse.model_validate(r) for r in rows]


@suites_router.post(
    "/{suite_id}/cases",
    response_model=EvalCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_case(
    suite_id: UUID,
    body: EvalCaseCreate,
    repo: TenantRepository[EvalSuite] = Depends(get_repo(EvalSuite)),
    session: AsyncSession = Depends(get_session),
) -> EvalCaseResponse:
    suite = await repo.get_or_404(suite_id)  # tenancy
    case = EvalCase(
        suite_id=suite.id,
        inputs=body.inputs,
        expected=body.expected,
        judge=body.judge,
        judge_config=body.judge_config,
    )
    session.add(case)
    await session.flush()
    return EvalCaseResponse.model_validate(case)


@suites_router.get("/{suite_id}/cases", response_model=list[EvalCaseResponse])
async def list_cases(
    suite_id: UUID,
    repo: TenantRepository[EvalSuite] = Depends(get_repo(EvalSuite)),
    session: AsyncSession = Depends(get_session),
) -> list[EvalCaseResponse]:
    await repo.get_or_404(suite_id)
    rows = (
        (
            await session.execute(
                select(EvalCase)
                .where(EvalCase.suite_id == suite_id)
                .order_by(EvalCase.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [EvalCaseResponse.model_validate(r) for r in rows]


@suites_router.post(
    "/{suite_id}/run",
    response_model=EvalBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def run_batch(
    suite_id: UUID,
    body: EvalBatchRunRequest,
    principal: Principal = Depends(get_principal),
    repo: TenantRepository[EvalSuite] = Depends(get_repo(EvalSuite)),
    session: AsyncSession = Depends(get_session),
) -> EvalBatchResponse:
    suite = await repo.get_or_404(suite_id)

    # Resolve cases (within the suite) and validate versions belong to a prompt
    # in the principal's org. A version_id from another org → 404.
    cases = (
        (await session.execute(select(EvalCase).where(EvalCase.suite_id == suite.id)))
        .scalars()
        .all()
    )
    if not cases:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="suite has no cases")

    versions = (
        (await session.execute(select(PromptVersion).where(PromptVersion.id.in_(body.version_ids))))
        .scalars()
        .all()
    )
    if len(versions) != len(body.version_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")
    # Cross-org check: a version's prompt must be in the principal's org.
    from promptforge_api.models import Prompt

    prompt_org_ids = {
        p.org_id
        for p in (
            (
                await session.execute(
                    select(Prompt).where(Prompt.id.in_({v.prompt_id for v in versions}))
                )
            ).scalars()
        )
    }
    if any(oid != principal.org_id for oid in prompt_org_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")

    total = len(cases) * len(versions)
    batch = EvalBatch(
        org_id=principal.org_id,
        suite_id=suite.id,
        version_ids=[str(v.id) for v in versions],
        total_jobs=total,
        completed_jobs=0,
        created_by=principal.user_id,
    )
    session.add(batch)
    await session.flush()
    await session.commit()  # the batch row must be visible to workers before we enqueue

    queue = Queue(get_session_factory())
    for version in versions:
        for case in cases:
            await queue.enqueue(
                "eval_case",
                {
                    "batch_id": str(batch.id),
                    "version_id": str(version.id),
                    "case_id": str(case.id),
                },
                batch_id=batch.id,
            )

    return EvalBatchResponse.model_validate(batch)


@batches_router.get("/{batch_id}", response_model=EvalBatchDetailResponse)
async def get_batch(
    batch_id: UUID,
    repo: TenantRepository[EvalBatch] = Depends(get_repo(EvalBatch)),
    session: AsyncSession = Depends(get_session),
) -> EvalBatchDetailResponse:
    batch = await repo.get_or_404(batch_id)
    rows = (
        (await session.execute(select(EvalResult).where(EvalResult.batch_id == batch.id)))
        .scalars()
        .all()
    )
    return EvalBatchDetailResponse(
        **EvalBatchResponse.model_validate(batch).model_dump(),
        results=[EvalResultResponse.model_validate(r) for r in rows],
    )


@batches_router.get("/{batch_id}/stream")
async def stream_batch(
    batch_id: UUID,
    repo: TenantRepository[EvalBatch] = Depends(get_repo(EvalBatch)),
) -> EventSourceResponse:
    """SSE: forwards pg_notify events for this batch's channel until the
    batch is done (or the client disconnects)."""
    batch = await repo.get_or_404(batch_id)
    engine = get_engine()
    channel = _batch_channel(batch.id)

    async def _events() -> AsyncIterator[dict[str, Any]]:
        # Subscribe via asyncpg LISTEN. We need a raw asyncpg connection because
        # SQLAlchemy doesn't expose LISTEN through its async API directly.
        raw = await engine.raw_connection()
        try:
            asyncpg_conn: Any = raw.driver_connection
            assert asyncpg_conn is not None, "raw_connection has no driver_connection"
            queue: asyncio.Queue[str] = asyncio.Queue()

            def _on_notify(_conn: object, _pid: int, _channel: str, payload: str) -> None:
                queue.put_nowait(payload)

            await asyncpg_conn.add_listener(channel, _on_notify)
            try:
                yield {
                    "event": "open",
                    "data": json.dumps({"batch_id": str(batch.id)}),
                }
                while True:
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    except TimeoutError:
                        # SSE clients (and proxies) drop on long silences. Heartbeat.
                        yield {"event": "ping", "data": "{}"}
                        continue
                    yield {"event": "result", "data": payload}
                    # If the batch flipped to done, emit a final event and stop.
                    try:
                        parsed = json.loads(payload)
                        if (
                            parsed.get("completed") is not None
                            and parsed.get("total") is not None
                            and parsed["completed"] >= parsed["total"]
                        ):
                            yield {"event": "done", "data": payload}
                            return
                    except (json.JSONDecodeError, TypeError):
                        continue
            finally:
                await asyncpg_conn.remove_listener(channel, _on_notify)
        finally:
            raw.close()

    return EventSourceResponse(_events())
