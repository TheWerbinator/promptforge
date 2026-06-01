"""Run a single eval case against a single PromptVersion.

The worker calls `run_eval_case(payload)` for each queue job of kind="eval_case".
Payload shape: {"batch_id": str, "version_id": str, "case_id": str}.

What this does, per job:
  1. Load Batch, Case, Version. Resolve effective judge (case override > suite default).
  2. Build PromptTemplate from version, render with case.inputs.
  3. Call call_llm and persist a Run row (failed-run pattern from phase 10).
  4. Run the judge against the output → score, passed, reasoning.
  5. Insert an EvalResult row keyed on (batch, version, case).
  6. Bump completed_jobs; if all (cases x versions) are done, flip status to done.
  7. NOTIFY the batch channel with a small status event (SSE fanout — phase 12).

Errors caught here are recorded into the EvalResult row, not raised — the
worker should treat the job as acked because the failure is durable. Re-raising
would requeue the job and we'd never converge.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from promptforge_api.core.prompts import (
    PromptTemplate,
    PromptValidationError,
    PromptVariable,
)
from promptforge_api.core.queue import _batch_channel
from promptforge_api.models import (
    EvalBatch,
    EvalBatchStatus,
    EvalCase,
    EvalSuite,
    JudgeKind,
    PromptVersion,
    Run,
)
from promptforge_api.services import llm as llm_service
from promptforge_api.services.judge import (
    JudgeOutcome,
    judge,
)


async def run_eval_case(
    payload: dict[str, Any],
    *,
    session_factory: async_sessionmaker[AsyncSession],
    user_api_key: str | None = None,
) -> None:
    """Process one eval-case job. Idempotent: re-running with the same payload
    overwrites the EvalResult row instead of duplicating it."""
    batch_id = UUID(str(payload["batch_id"]))
    version_id = UUID(str(payload["version_id"]))
    case_id = UUID(str(payload["case_id"]))

    async with session_factory() as session:
        batch = await session.get(EvalBatch, batch_id)
        version = await session.get(PromptVersion, version_id)
        case = await session.get(EvalCase, case_id)
        if batch is None or version is None or case is None:
            return  # batch or its inputs deleted mid-flight; nothing useful to do.

        suite = await session.get(EvalSuite, case.suite_id)
        effective_judge: JudgeKind = case.judge or (
            suite.judge_default if suite else JudgeKind.EXACT
        )

        run, output, output_error = await _execute_run(
            session, batch=batch, version=version, case=case, user_api_key=user_api_key
        )

        outcome = await _grade(
            kind=effective_judge,
            output=output or "",
            expected=case.expected,
            config=case.judge_config,
            output_error=output_error,
            user_api_key=user_api_key,
        )

        await _upsert_result(
            session,
            batch_id=batch.id,
            version_id=version.id,
            case_id=case.id,
            run_id=run.id if run else None,
            score=outcome.score,
            passed=outcome.passed,
            reasoning=outcome.reasoning,
        )

        # Atomic increment + status flip when complete.
        completed = await _bump_progress(session, batch.id)
        if completed >= batch.total_jobs and batch.total_jobs > 0:
            await session.execute(
                text("UPDATE eval_batches SET status = 'done' WHERE id = :id AND status <> 'done'"),
                {"id": batch.id},
            )

        await session.commit()

        await _notify(
            session,
            batch.id,
            {
                "kind": "result",
                "case_id": str(case.id),
                "version_id": str(version.id),
                "score": outcome.score,
                "passed": outcome.passed,
                "completed": completed,
                "total": batch.total_jobs,
            },
        )


async def _execute_run(
    session: AsyncSession,
    *,
    batch: EvalBatch,
    version: PromptVersion,
    case: EvalCase,
    user_api_key: str | None,
) -> tuple[Run | None, str | None, str | None]:
    """Render + call LLM + persist a Run row. Returns (run, output, error)."""
    try:
        template = PromptTemplate(
            body=version.body,
            variables=[PromptVariable(**v) for v in version.variables],
        )
        rendered = template.render(**case.inputs)
    except PromptValidationError as exc:
        # Template/input mismatch — persist a Run row w/ error and return.
        run = Run(
            org_id=batch.org_id,
            version_id=version.id,
            model="",
            inputs=case.inputs,
            output=None,
            error=f"template render failed: {exc}",
        )
        session.add(run)
        await session.flush()
        return run, None, str(exc)

    # Pick the run model from the case's judge_config, default to gpt-4o-mini.
    # (Per-case overrides are nice for "test prompt A on cheap, prompt B on big".)
    run_model = str(case.judge_config.get("run_model", "openai/gpt-4o-mini"))

    output: str | None = None
    error: str | None = None
    input_tokens = output_tokens = latency_ms = 0
    cost_usd: float | None = None
    provider_response: dict[str, Any] | None = None

    try:
        result = await llm_service.call_llm(
            run_model,
            [{"role": "user", "content": rendered}],
            user_api_key=user_api_key,
        )
        output = result.text
        input_tokens = result.input_tokens
        output_tokens = result.output_tokens
        cost_usd = result.cost_usd
        latency_ms = result.latency_ms
        provider_response = result.provider_response
    except llm_service.LLMCallError as exc:
        error = str(exc)

    run = Run(
        org_id=batch.org_id,
        version_id=version.id,
        model=run_model,
        inputs=case.inputs,
        output=output,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        provider_response=provider_response,
        error=error,
    )
    session.add(run)
    await session.flush()
    return run, output, error


async def _grade(
    *,
    kind: JudgeKind,
    output: str,
    expected: dict[str, Any],
    config: dict[str, Any],
    output_error: str | None,
    user_api_key: str | None,
) -> JudgeOutcome:
    if output_error is not None:
        return JudgeOutcome(score=0.0, passed=False, reasoning=f"run failed: {output_error}")
    return await judge(
        kind, output=output, expected=expected, config=config, user_api_key=user_api_key
    )


async def _upsert_result(
    session: AsyncSession,
    *,
    batch_id: UUID,
    version_id: UUID,
    case_id: UUID,
    run_id: UUID | None,
    score: float,
    passed: bool,
    reasoning: str | None,
) -> None:
    """Insert-or-update keyed on the unique(batch, version, case) constraint.
    Re-running a job overwrites the prior result rather than duplicating."""
    await session.execute(
        text(
            "INSERT INTO eval_results "
            "(id, batch_id, version_id, case_id, run_id, score, passed, "
            " judge_reasoning, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :batch_id, :version_id, :case_id, :run_id, "
            "        :score, :passed, :reasoning, now(), now()) "
            "ON CONFLICT (batch_id, version_id, case_id) DO UPDATE SET "
            "  run_id = EXCLUDED.run_id, "
            "  score = EXCLUDED.score, "
            "  passed = EXCLUDED.passed, "
            "  judge_reasoning = EXCLUDED.judge_reasoning, "
            "  updated_at = now()"
        ),
        {
            "batch_id": batch_id,
            "version_id": version_id,
            "case_id": case_id,
            "run_id": run_id,
            "score": score,
            "passed": passed,
            "reasoning": reasoning,
        },
    )


async def _bump_progress(session: AsyncSession, batch_id: UUID) -> int:
    """Atomically increment completed_jobs and return the new count."""
    result = await session.execute(
        text(
            "UPDATE eval_batches SET completed_jobs = completed_jobs + 1 "
            "WHERE id = :id RETURNING completed_jobs"
        ),
        {"id": batch_id},
    )
    return int(result.scalar_one())


async def _notify(session: AsyncSession, batch_id: UUID, event: dict[str, Any]) -> None:
    """Emit a small SSE-relayed event on the batch's NOTIFY channel."""
    payload = json.dumps(event)
    if len(payload) > 7800:
        return  # silently skip — UI will refetch on next event
    await session.execute(
        text("SELECT pg_notify(:c, :p)"),
        {"c": _batch_channel(batch_id), "p": payload},
    )


# Exposed for ad-hoc usage from the worker handler. The worker passes its
# session factory + (optional) BYOK key.
__all__ = ["EvalBatch", "EvalBatchStatus", "run_eval_case"]
