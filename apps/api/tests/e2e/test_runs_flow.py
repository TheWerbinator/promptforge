"""End-to-end run flow with services.llm.call_llm mocked.

We never hit a real provider — call_llm is monkeypatched per test. The full
HTTP path is real (auth, tenancy resolution, template render, persist Run).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from promptforge_api.services import llm as llm_service
from promptforge_api.services.llm import LLMCallError, LLMResponse

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


SIGNUP_BODY = {
    "email": "runner@example.com",
    "password": "Sup3rSecret!",
    "display_name": "Runner",
}


async def _signup(client: AsyncClient) -> dict:
    r = await client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    assert r.status_code == 201, r.text
    return r.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_prompt_with_version(client: AsyncClient, headers: dict) -> dict:
    payload = {
        "name": "summarize",
        "body": "Summarize:\n{{document}}",
        "variables": [{"name": "document", "type": "str", "required": True}],
    }
    r = await client.post("/api/v1/prompts", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _stub_call_llm(text: str = "summarized!", **overrides: Any):
    async def _fake(model: str, messages: list[dict], **kwargs: Any) -> LLMResponse:
        return LLMResponse(
            text=text,
            model=model,
            input_tokens=overrides.get("input_tokens", 50),
            output_tokens=overrides.get("output_tokens", 12),
            cost_usd=overrides.get("cost_usd", 0.0001),
            latency_ms=overrides.get("latency_ms", 120),
            provider_response={"raw": True},
        )

    return _fake


async def test_run_happy_path_persists_run(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    prompt = await _create_prompt_with_version(api_client, headers)
    version_id = prompt["latest_version"]["id"]

    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm())

    r = await api_client.post(
        f"/api/v1/versions/{version_id}/run",
        headers=headers,
        json={
            "model": "openai/gpt-4o-mini",
            "inputs": {"document": "Lorem ipsum dolor sit amet"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["output"] == "summarized!"
    assert body["model"] == "openai/gpt-4o-mini"
    assert body["input_tokens"] == 50
    assert body["error"] is None
    assert body["version_id"] == version_id

    # Round-trip via GET.
    get_r = await api_client.get(f"/api/v1/runs/{body['id']}", headers=headers)
    assert get_r.status_code == 200
    assert get_r.json()["id"] == body["id"]


async def test_run_with_invalid_variables_returns_422(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    prompt = await _create_prompt_with_version(api_client, headers)
    version_id = prompt["latest_version"]["id"]
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm())

    r = await api_client.post(
        f"/api/v1/versions/{version_id}/run",
        headers=headers,
        json={"model": "openai/gpt-4o-mini", "inputs": {}},  # missing 'document'
    )
    assert r.status_code == 422
    assert "errors" in r.json()["detail"]


async def test_run_llm_failure_still_persists_run_with_error(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    prompt = await _create_prompt_with_version(api_client, headers)
    version_id = prompt["latest_version"]["id"]

    async def _boom(*_args: Any, **_kwargs: Any) -> LLMResponse:
        raise LLMCallError("provider down")

    monkeypatch.setattr(llm_service, "call_llm", _boom)

    r = await api_client.post(
        f"/api/v1/versions/{version_id}/run",
        headers=headers,
        json={
            "model": "openai/gpt-4o-mini",
            "inputs": {"document": "anything"},
        },
    )
    assert r.status_code == 201  # the Run row was persisted
    assert r.json()["output"] is None
    assert "provider down" in r.json()["error"]


async def test_run_on_other_orgs_version_returns_404(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm())

    # Org A creates a prompt + version.
    a = await _signup(api_client)
    a_headers = _headers(a["access_token"])
    prompt = await _create_prompt_with_version(api_client, a_headers)
    version_id = prompt["latest_version"]["id"]

    # Org B (different signup) attempts to run it.
    api_client.cookies.clear()
    b_resp = await api_client.post(
        "/api/v1/auth/signup",
        json={"email": "b@example.com", "password": "Sup3rSecret!"},
    )
    b_token = b_resp.json()["access_token"]

    r = await api_client.post(
        f"/api/v1/versions/{version_id}/run",
        headers=_headers(b_token),
        json={"model": "openai/gpt-4o-mini", "inputs": {"document": "x"}},
    )
    assert r.status_code == 404


async def test_get_run_other_org_returns_404(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm())

    a = await _signup(api_client)
    a_headers = _headers(a["access_token"])
    prompt = await _create_prompt_with_version(api_client, a_headers)
    version_id = prompt["latest_version"]["id"]
    created = await api_client.post(
        f"/api/v1/versions/{version_id}/run",
        headers=a_headers,
        json={"model": "openai/gpt-4o-mini", "inputs": {"document": "x"}},
    )
    run_id = created.json()["id"]

    api_client.cookies.clear()
    b_resp = await api_client.post(
        "/api/v1/auth/signup",
        json={"email": "b2@example.com", "password": "Sup3rSecret!"},
    )
    r = await api_client.get(
        f"/api/v1/runs/{run_id}", headers=_headers(b_resp.json()["access_token"])
    )
    assert r.status_code == 404


async def test_run_requires_auth(api_client: AsyncClient) -> None:
    r = await api_client.post(
        "/api/v1/versions/00000000-0000-0000-0000-000000000000/run",
        json={"model": "openai/gpt-4o-mini", "inputs": {}},
    )
    assert r.status_code == 401


async def test_run_unknown_version_returns_404(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    monkeypatch.setattr(llm_service, "call_llm", _stub_call_llm())

    r = await api_client.post(
        "/api/v1/versions/00000000-0000-0000-0000-000000000000/run",
        headers=headers,
        json={"model": "openai/gpt-4o-mini", "inputs": {}},
    )
    assert r.status_code == 404
