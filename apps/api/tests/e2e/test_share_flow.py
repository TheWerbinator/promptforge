"""E2E for public share tokens: prompt + eval-batch links, revoke, expiry, tenancy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from promptforge_api.core.db import get_session_factory
from promptforge_api.core.queue import Queue
from promptforge_api.models import ShareToken
from promptforge_api.services import llm as llm_service
from promptforge_api.services.llm import LLMResponse
from promptforge_api.workers.eval_worker import _run_one

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


def _stub_call_llm(text: str = "hello world"):
    async def _fake(model: str, _messages: list, **_kwargs: Any) -> LLMResponse:
        return LLMResponse(
            text=text,
            model=model,
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            latency_ms=1,
            provider_response={},
        )

    return _fake


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signup(client: AsyncClient, email: str = "sharer@example.com") -> str:
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Sup3rSecret!", "display_name": "S"},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["access_token"])


async def _create_prompt(client: AsyncClient, h: dict[str, str]) -> str:
    r = await client.post(
        "/api/v1/prompts",
        headers=h,
        json={
            "name": "greet",
            "body": "Greet {{name}}",
            "variables": [{"name": "name", "type": "str"}],
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _drain() -> None:
    queue = Queue(get_session_factory())
    for _ in range(10):
        jobs = await queue.claim("eval_case", limit=10)
        if not jobs:
            return
        for job in jobs:
            await _run_one(job)


async def test_prompt_share_serves_public_readonly_view(api_client: AsyncClient) -> None:
    h = _h(await _signup(api_client))
    prompt_id = await _create_prompt(api_client, h)

    created = await api_client.post(
        "/api/v1/shares",
        headers=h,
        json={"resource_type": "prompt", "resource_id": prompt_id},
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    assert token

    # No auth header — public link works for anyone.
    pub = await api_client.get(f"/api/v1/public/share/{token}")
    assert pub.status_code == 200, pub.text
    body = pub.json()
    assert body["resource_type"] == "prompt"
    assert body["prompt"]["name"] == "greet"
    assert body["prompt"]["latest_version"]["body"] == "Greet {{name}}"
    assert body["eval_batch"] is None
    # Public projection must not leak workspace internals.
    assert "org_id" not in body["prompt"]
    assert "created_by" not in body["prompt"]


async def test_eval_batch_share_serves_public_report(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm("hello world"))
    h = _h(await _signup(api_client))

    prompt = (
        await api_client.post(
            "/api/v1/prompts",
            headers=h,
            json={"name": "p", "body": "x", "variables": []},
        )
    ).json()
    version_id = prompt["latest_version"]["id"]
    suite = (
        await api_client.post(
            "/api/v1/eval-suites", headers=h, json={"name": "s", "judge_default": "contains"}
        )
    ).json()
    await api_client.post(
        f"/api/v1/eval-suites/{suite['id']}/cases",
        headers=h,
        json={"inputs": {}, "expected": {"value": "hello"}},
    )
    batch = (
        await api_client.post(
            f"/api/v1/eval-suites/{suite['id']}/run",
            headers=h,
            json={"version_ids": [version_id]},
        )
    ).json()
    await _drain()

    token = (
        await api_client.post(
            "/api/v1/shares",
            headers=h,
            json={"resource_type": "eval_batch", "resource_id": batch["id"]},
        )
    ).json()["token"]

    pub = await api_client.get(f"/api/v1/public/share/{token}")
    assert pub.status_code == 200, pub.text
    report = pub.json()["eval_batch"]
    assert report["status"] == "done"
    assert report["pass_rate"] == 1.0
    assert len(report["results"]) == 1
    assert report["results"][0]["passed"] is True


async def test_revoked_share_returns_404(api_client: AsyncClient) -> None:
    h = _h(await _signup(api_client))
    prompt_id = await _create_prompt(api_client, h)
    created = (
        await api_client.post(
            "/api/v1/shares",
            headers=h,
            json={"resource_type": "prompt", "resource_id": prompt_id},
        )
    ).json()
    token, share_id = created["token"], created["id"]

    assert (await api_client.get(f"/api/v1/public/share/{token}")).status_code == 200
    assert (await api_client.delete(f"/api/v1/shares/{share_id}", headers=h)).status_code == 204
    assert (await api_client.get(f"/api/v1/public/share/{token}")).status_code == 404
    # Double-revoke is a 404.
    assert (await api_client.delete(f"/api/v1/shares/{share_id}", headers=h)).status_code == 404


async def test_expired_share_returns_404(api_client: AsyncClient) -> None:
    h = _h(await _signup(api_client))
    prompt_id = await _create_prompt(api_client, h)
    created = (
        await api_client.post(
            "/api/v1/shares",
            headers=h,
            json={"resource_type": "prompt", "resource_id": prompt_id, "expires_in_days": 7},
        )
    ).json()
    token = created["token"]

    # Backdate the expiry past now.
    async with get_session_factory()() as s:
        row = await s.get(ShareToken, UUID(created["id"]))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await s.commit()

    assert (await api_client.get(f"/api/v1/public/share/{token}")).status_code == 404


async def test_create_share_for_cross_org_resource_404(api_client: AsyncClient) -> None:
    # Org A owns a prompt.
    a_h = _h(await _signup(api_client, email="sa@example.com"))
    a_prompt = await _create_prompt(api_client, a_h)

    # Org B can't mint a share for it.
    api_client.cookies.clear()
    b_h = _h(await _signup(api_client, email="sb@example.com"))
    r = await api_client.post(
        "/api/v1/shares",
        headers=b_h,
        json={"resource_type": "prompt", "resource_id": a_prompt},
    )
    assert r.status_code == 404


async def test_create_share_requires_auth(api_client: AsyncClient) -> None:
    r = await api_client.post(
        "/api/v1/shares",
        json={"resource_type": "prompt", "resource_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 401


async def test_public_unknown_token_404(api_client: AsyncClient) -> None:
    assert (await api_client.get("/api/v1/public/share/nope-not-a-token")).status_code == 404
