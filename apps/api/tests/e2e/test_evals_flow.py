"""E2E happy path for eval suite + case + batch run with mocked LLM.

This drives the full flow through the real ASGI app + real Postgres via
testcontainers, then runs the worker's eval handler in-process to drain the
queue (we don't spin up the worker subprocess — the same handler function is
just called directly).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from promptforge_api.api.v1.evals import eval_event_stream
from promptforge_api.core.db import get_engine, get_session_factory
from promptforge_api.core.queue import Queue
from promptforge_api.services import llm as llm_service
from promptforge_api.services.llm import LLMResponse
from promptforge_api.workers.eval_worker import _consume_forever, _run_one

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


SIGNUP_BODY = {
    "email": "eval-runner@example.com",
    "password": "Sup3rSecret!",
    "display_name": "Eval",
}


def _stub_call_llm(text: str = "hello world"):
    async def _fake(model: str, _messages: list, **_kwargs: Any) -> LLMResponse:
        return LLMResponse(
            text=text,
            model=model,
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0001,
            latency_ms=50,
            provider_response={},
        )

    return _fake


async def _signup(client: AsyncClient, email: str = SIGNUP_BODY["email"]) -> dict:
    r = await client.post("/api/v1/auth/signup", json={**SIGNUP_BODY, "email": email})
    assert r.status_code == 201, r.text
    return r.json()


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _drain_queue(kind: str = "eval_case", *, max_iterations: int = 20) -> None:
    """Pull and run any queued eval-case jobs synchronously, the way the worker
    would. Stops once the queue is empty or max_iterations is hit."""
    queue = Queue(get_session_factory())
    for _ in range(max_iterations):
        jobs = await queue.claim(kind, limit=10)
        if not jobs:
            return
        for job in jobs:
            await _run_one(job)


async def _run_next_job(kind: str = "eval_case") -> int:
    """Claim and run a single queued job. Returns how many ran (0 or 1).

    Lets a test advance a batch one case at a time so the SSE stream can be
    observed mid-flight (before the batch reaches its terminal state)."""
    queue = Queue(get_session_factory())
    jobs = await queue.claim(kind, limit=1)
    for job in jobs:
        await _run_one(job)
    return len(jobs)


async def _make_two_case_batch(client: AsyncClient, h: dict[str, str]) -> str:
    """Prompt + version + suite + two passing cases + run. Returns the batch id."""
    prompt = (
        await client.post(
            "/api/v1/prompts",
            headers=h,
            json={
                "name": "greet",
                "body": "Greet {{name}}",
                "variables": [{"name": "name", "type": "str"}],
            },
        )
    ).json()
    version_id = prompt["latest_version"]["id"]
    suite = (
        await client.post(
            "/api/v1/eval-suites",
            headers=h,
            json={"name": "greet-quality", "judge_default": "contains"},
        )
    ).json()
    for name in ("Jake", "Casey"):
        await client.post(
            f"/api/v1/eval-suites/{suite['id']}/cases",
            headers=h,
            json={"inputs": {"name": name}, "expected": {"value": "hello"}},
        )
    batch = (
        await client.post(
            f"/api/v1/eval-suites/{suite['id']}/run",
            headers=h,
            json={"version_ids": [version_id]},
        )
    ).json()
    return str(batch["id"])


async def test_create_suite_add_cases_run_batch_persists_results(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm("hello world"))

    auth = await _signup(api_client)
    token = auth["access_token"]
    h = _h(token)

    # Prompt + version.
    prompt = (
        await api_client.post(
            "/api/v1/prompts",
            headers=h,
            json={
                "name": "greet",
                "body": "Greet {{name}}",
                "variables": [{"name": "name", "type": "str"}],
            },
        )
    ).json()
    version_id = prompt["latest_version"]["id"]

    # Suite.
    suite = (
        await api_client.post(
            "/api/v1/eval-suites",
            headers=h,
            json={"name": "greet-quality", "judge_default": "contains"},
        )
    ).json()
    suite_id = suite["id"]

    # Two cases, both expecting "hello" substring.
    await api_client.post(
        f"/api/v1/eval-suites/{suite_id}/cases",
        headers=h,
        json={
            "inputs": {"name": "Jake"},
            "expected": {"value": "hello"},
        },
    )
    await api_client.post(
        f"/api/v1/eval-suites/{suite_id}/cases",
        headers=h,
        json={
            "inputs": {"name": "Casey"},
            "expected": {"value": "hello"},
        },
    )

    # Run.
    run_resp = await api_client.post(
        f"/api/v1/eval-suites/{suite_id}/run",
        headers=h,
        json={"version_ids": [version_id]},
    )
    assert run_resp.status_code == 201, run_resp.text
    batch = run_resp.json()
    assert batch["total_jobs"] == 2
    assert batch["status"] == "queued"
    batch_id = batch["id"]

    # Drain the queue inline (simulates the worker process).
    await _drain_queue()

    # Final batch detail should show 2 passed results and status=done.
    detail = (await api_client.get(f"/api/v1/eval-batches/{batch_id}", headers=h)).json()
    assert detail["status"] == "done", detail
    assert detail["completed_jobs"] == 2
    assert len(detail["results"]) == 2
    assert all(r["passed"] is True for r in detail["results"])
    assert all(r["score"] == 1.0 for r in detail["results"])


async def test_run_batch_with_no_cases_returns_400(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm())

    auth = await _signup(api_client)
    h = _h(auth["access_token"])

    prompt = (
        await api_client.post(
            "/api/v1/prompts",
            headers=h,
            json={"name": "p", "body": "x", "variables": []},
        )
    ).json()
    suite = (
        await api_client.post("/api/v1/eval-suites", headers=h, json={"name": "empty-suite"})
    ).json()

    r = await api_client.post(
        f"/api/v1/eval-suites/{suite['id']}/run",
        headers=h,
        json={"version_ids": [prompt["latest_version"]["id"]]},
    )
    assert r.status_code == 400


async def test_run_batch_with_cross_org_version_returns_404(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm())

    # Org A creates a prompt.
    a = await _signup(api_client, email="ea@example.com")
    a_h = _h(a["access_token"])
    a_prompt = (
        await api_client.post(
            "/api/v1/prompts",
            headers=a_h,
            json={"name": "p", "body": "x", "variables": []},
        )
    ).json()

    # Org B: new signup, builds a suite + case.
    api_client.cookies.clear()
    b = await _signup(api_client, email="eb@example.com")
    b_h = _h(b["access_token"])
    b_suite = (await api_client.post("/api/v1/eval-suites", headers=b_h, json={"name": "s"})).json()
    await api_client.post(
        f"/api/v1/eval-suites/{b_suite['id']}/cases",
        headers=b_h,
        json={"inputs": {}, "expected": {"value": "x"}},
    )

    # B tries to run their suite against A's version → 404.
    r = await api_client.post(
        f"/api/v1/eval-suites/{b_suite['id']}/run",
        headers=b_h,
        json={"version_ids": [a_prompt["latest_version"]["id"]]},
    )
    assert r.status_code == 404


async def test_failed_llm_call_still_records_failed_result(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from promptforge_api.services.llm import LLMCallError

    async def _boom(*_args: Any, **_kwargs: Any) -> LLMResponse:
        raise LLMCallError("provider unreachable")

    monkeypatch.setattr(llm_service, "call_llm", _boom)

    auth = await _signup(api_client)
    h = _h(auth["access_token"])
    prompt = (
        await api_client.post(
            "/api/v1/prompts",
            headers=h,
            json={"name": "p", "body": "x", "variables": []},
        )
    ).json()
    suite = (await api_client.post("/api/v1/eval-suites", headers=h, json={"name": "s"})).json()
    await api_client.post(
        f"/api/v1/eval-suites/{suite['id']}/cases",
        headers=h,
        json={"inputs": {}, "expected": {"value": "x"}},
    )
    batch = (
        await api_client.post(
            f"/api/v1/eval-suites/{suite['id']}/run",
            headers=h,
            json={"version_ids": [prompt["latest_version"]["id"]]},
        )
    ).json()

    await _drain_queue()

    detail = (await api_client.get(f"/api/v1/eval-batches/{batch['id']}", headers=h)).json()
    # Even with the LLM down, we converged: status=done, one result, passed=False.
    assert detail["status"] == "done"
    assert len(detail["results"]) == 1
    assert detail["results"][0]["passed"] is False
    assert "run failed" in (detail["results"][0]["judge_reasoning"] or "")


# ----- SSE stream (phase 12) -----------------------------------------------------------
#
# httpx's ASGITransport buffers the entire response before returning, so a live
# SSE stream can't be consumed through `api_client` while the worker concurrently
# produces NOTIFYs — the app would block forever waiting for events the test can't
# send. These tests drive the transport-agnostic `eval_event_stream` generator
# directly against the real Postgres LISTEN/NOTIFY channel instead. The HTTP layer
# (routing + EventSourceResponse wrapping) is covered by the already-done test,
# which is safe through ASGITransport because that generator returns immediately.


async def test_stream_forwards_live_result_and_done_events(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm("hello world"))
    auth = await _signup(api_client)
    h = _h(auth["access_token"])
    batch_id = await _make_two_case_batch(api_client, h)

    stream = eval_event_stream(get_engine(), UUID(batch_id))
    try:
        # Pull `open` first: this guarantees the LISTEN is registered before any
        # NOTIFY is produced, so we can't miss an event to a subscribe-vs-emit race.
        opened = await stream.__anext__()
        assert opened["event"] == "open"

        # Finish one case → exactly one `result` event, batch still in progress.
        assert await _run_next_job() == 1
        first = await asyncio.wait_for(stream.__anext__(), timeout=15.0)
        assert first["event"] == "result"
        assert json.loads(first["data"])["completed"] == 1

        # Finish the rest → final `result` then a terminal `done`.
        await _drain_queue()
        second = await asyncio.wait_for(stream.__anext__(), timeout=15.0)
        assert second["event"] == "result"
        done = await asyncio.wait_for(stream.__anext__(), timeout=15.0)
        assert done["event"] == "done"
        done_payload = json.loads(done["data"])
        assert done_payload["completed"] == 2
        assert done_payload["total"] == 2
    finally:
        await stream.aclose()


async def test_stream_short_circuits_when_batch_already_done(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm("hello world"))
    auth = await _signup(api_client)
    h = _h(auth["access_token"])
    batch_id = await _make_two_case_batch(api_client, h)

    # Batch finishes before anyone subscribes (the fast-batch race).
    await _drain_queue()

    stream = eval_event_stream(get_engine(), UUID(batch_id))

    async def _collect() -> list[dict[str, Any]]:
        return [event async for event in stream]

    events = await asyncio.wait_for(_collect(), timeout=15.0)
    # No live result events to forward — just open then an immediate done, so the
    # client isn't left hanging on a now-silent channel until the heartbeat.
    assert [e["event"] for e in events] == ["open", "done"]
    assert json.loads(events[-1]["data"])["status"] == "done"


async def test_stream_endpoint_serves_sse_over_http(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end through the real route + EventSourceResponse. Uses an
    already-done batch so the generator returns promptly (ASGITransport buffers
    the whole response, so a still-running stream would never return here)."""
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm("hello world"))
    auth = await _signup(api_client)
    h = _h(auth["access_token"])
    batch_id = await _make_two_case_batch(api_client, h)
    await _drain_queue()

    resp = await api_client.get(f"/api/v1/eval-batches/{batch_id}/stream", headers=h)

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: open" in resp.text
    assert "event: done" in resp.text


async def test_real_worker_consume_loop_drives_sse_stream(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full chain: enqueue → real worker consume loop claims off the queue →
    handler → committed NOTIFY → SSE subscriber receives live events.

    The other SSE tests drive the handler in-process (`_run_one`/`_drain_queue`),
    which proves the handler logic but NOT that the worker's claim/dispatch poll
    loop wires up correctly. This runs the actual `_consume_forever` loop against
    the real queue. (True subprocess boot + SIGINT/SIGTERM handling is left to the
    Phase 16 deploy smoke — that's process plumbing, not application logic.)"""
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm("hello world"))
    auth = await _signup(api_client)
    h = _h(auth["access_token"])
    batch_id = await _make_two_case_batch(api_client, h)  # jobs are now queued

    stream = eval_event_stream(get_engine(), UUID(batch_id))
    try:
        # Subscribe before the worker runs so we can't miss the live events.
        opened = await stream.__anext__()
        assert opened["event"] == "open"

        stop = asyncio.Event()
        worker = asyncio.create_task(_consume_forever(Queue(get_session_factory()), stop))

        events: list[dict[str, Any]] = []

        async def _collect_until_done() -> None:
            async for event in stream:
                events.append(event)
                if event["event"] == "done":
                    return

        try:
            await asyncio.wait_for(_collect_until_done(), timeout=20.0)
        finally:
            stop.set()
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await worker

        kinds = [e["event"] for e in events]
        assert kinds.count("result") == 2
        assert kinds[-1] == "done"
        assert json.loads(events[-1]["data"])["completed"] == 2
    finally:
        await stream.aclose()


async def test_stream_cross_org_batch_returns_404(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm("hello world"))

    # Org A owns the batch.
    a = await _signup(api_client, email="sa@example.com")
    a_batch = await _make_two_case_batch(api_client, _h(a["access_token"]))

    # Org B must not be able to stream it — tenancy returns 404, never 403.
    api_client.cookies.clear()
    b = await _signup(api_client, email="sb@example.com")
    resp = await api_client.get(
        f"/api/v1/eval-batches/{a_batch}/stream", headers=_h(b["access_token"])
    )
    assert resp.status_code == 404
