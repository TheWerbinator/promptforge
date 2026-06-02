"""E2E for demo mode: login, read-only enforcement, free-run quota, quota endpoint.

Demo data is seeded directly via the module-global session factory (same Postgres
container the app talks to) since a demo account can't be created through the API.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from promptforge_api.core.db import get_session_factory
from promptforge_api.core.security import hash_password
from promptforge_api.models import Membership, Org, OrgRole, Prompt, PromptVersion, User
from promptforge_api.services import llm as llm_service
from promptforge_api.services.llm import LLMResponse

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

DEMO_EMAIL = "demo@promptforge.dev"  # matches Settings.demo_email default


def _stub_call_llm(text: str = "hi"):
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


async def _seed_demo(*, with_prompt: bool = False) -> dict[str, UUID]:
    """Seed the demo user + Demo Corp org + DEMO membership (+ optional prompt)."""
    factory = get_session_factory()
    async with factory() as s:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password("demo-password"),
            display_name="Demo",
            is_active=True,
        )
        s.add(user)
        await s.flush()
        org = Org(name="Demo Corp", slug="demo-corp")
        s.add(org)
        await s.flush()
        s.add(Membership(user_id=user.id, org_id=org.id, role=OrgRole.DEMO))
        ids = {"user_id": user.id, "org_id": org.id}
        if with_prompt:
            prompt = Prompt(name="welcome", org_id=org.id, created_by=user.id)
            s.add(prompt)
            await s.flush()
            version = PromptVersion(
                prompt_id=prompt.id, version=1, body="Say hi", variables=[], created_by=user.id
            )
            s.add(version)
            await s.flush()
            ids["version_id"] = version.id
        await s.commit()
        return ids


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _demo_token(client: AsyncClient) -> str:
    r = await client.post("/api/v1/demo/login")
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


async def test_demo_login_returns_readonly_session(api_client: AsyncClient) -> None:
    await _seed_demo()
    r = await api_client.post("/api/v1/demo/login")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "demo"
    assert body["org"]["slug"] == "demo-corp"
    assert body["free_runs_remaining"] == 5
    assert body["access_token"]

    # The session works for reads.
    me = await api_client.get("/api/v1/auth/me", headers=_h(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["role"] == "demo"


async def test_demo_login_503_when_not_seeded(api_client: AsyncClient) -> None:
    r = await api_client.post("/api/v1/demo/login")
    assert r.status_code == 503


async def test_demo_is_read_only(api_client: AsyncClient) -> None:
    await _seed_demo()
    h = _h(await _demo_token(api_client))

    # Reads are allowed.
    assert (await api_client.get("/api/v1/prompts", headers=h)).status_code == 200

    # Writes are blocked with 403.
    assert (
        await api_client.post(
            "/api/v1/prompts", headers=h, json={"name": "x", "body": "y", "variables": []}
        )
    ).status_code == 403
    assert (
        await api_client.post("/api/v1/eval-suites", headers=h, json={"name": "s"})
    ).status_code == 403
    assert (
        await api_client.post("/api/v1/auth/api-keys", headers=h, json={"name": "k"})
    ).status_code == 403


async def test_demo_free_runs_then_requires_byok(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm())
    ids = await _seed_demo(with_prompt=True)
    h = _h(await _demo_token(api_client))
    run_url = f"/api/v1/versions/{ids['version_id']}/run"
    run_body = {"model": "openai/gpt-4o-mini", "inputs": {}}

    # 5 free hosted-key runs succeed.
    for i in range(5):
        r = await api_client.post(run_url, headers=h, json=run_body)
        assert r.status_code == 201, f"run {i} failed: {r.text}"

    # 6th without a key is refused with 402 (quota exhausted).
    blocked = await api_client.post(run_url, headers=h, json=run_body)
    assert blocked.status_code == 402
    assert "free demo runs" in blocked.json()["detail"]

    # BYOK bypasses the quota entirely.
    byok = await api_client.post(run_url, headers={**h, "X-Provider-Key": "sk-test"}, json=run_body)
    assert byok.status_code == 201


async def test_demo_quota_endpoint_tracks_usage(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm())
    ids = await _seed_demo(with_prompt=True)
    h = _h(await _demo_token(api_client))

    start = await api_client.get("/api/v1/demo/quota", headers=h)
    assert start.status_code == 200
    assert start.json() == {"limit": 5, "used": 0, "remaining": 5}

    run_url = f"/api/v1/versions/{ids['version_id']}/run"
    run_body = {"model": "openai/gpt-4o-mini", "inputs": {}}
    for _ in range(2):
        await api_client.post(run_url, headers=h, json=run_body)

    after = await api_client.get("/api/v1/demo/quota", headers=h)
    assert after.json() == {"limit": 5, "used": 2, "remaining": 3}


async def test_demo_login_rate_limited(api_client: AsyncClient) -> None:
    await _seed_demo()
    # Default limit is 5/minute; the 6th login from the same IP is throttled.
    statuses = []
    for _ in range(6):
        statuses.append((await api_client.post("/api/v1/demo/login")).status_code)
    assert statuses[:5] == [200, 200, 200, 200, 200]
    assert statuses[5] == 429
