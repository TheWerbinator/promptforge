"""E2E happy path for eval suite + case + batch run with mocked LLM.

This drives the full flow through the real ASGI app + real Postgres via
testcontainers, then runs the worker's eval handler in-process to drain the
queue (we don't spin up the worker subprocess — the same handler function is
just called directly).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from promptforge_api.core.db import get_session_factory
from promptforge_api.core.queue import Queue
from promptforge_api.services import llm as llm_service
from promptforge_api.services.llm import LLMResponse
from promptforge_api.workers.eval_worker import _run_one

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
