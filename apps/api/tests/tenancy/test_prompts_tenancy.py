"""Tenancy contract for Prompt + PromptVersion."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.tenancy._helpers import make_two_orgs

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def _create_prompt(client: AsyncClient, headers: dict[str, str], name: str) -> dict:
    response = await client.post(
        "/api/v1/prompts",
        headers=headers,
        json={
            "name": name,
            "body": "hello {{x}}",
            "variables": [{"name": "x", "type": "str", "required": True}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_list_excludes_other_orgs_prompts(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    await _create_prompt(api_client, orgs.a.headers, "a-prompt")

    response = await api_client.get("/api/v1/prompts", headers=orgs.b.headers)
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_get_other_orgs_prompt_returns_404(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    prompt = await _create_prompt(api_client, orgs.a.headers, "a-prompt")
    response = await api_client.get(f"/api/v1/prompts/{prompt['id']}", headers=orgs.b.headers)
    assert response.status_code == 404


async def test_patch_other_orgs_prompt_returns_404(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    prompt = await _create_prompt(api_client, orgs.a.headers, "a-prompt")
    response = await api_client.patch(
        f"/api/v1/prompts/{prompt['id']}",
        headers=orgs.b.headers,
        json={"description": "hijack"},
    )
    assert response.status_code == 404


async def test_delete_other_orgs_prompt_returns_404(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    prompt = await _create_prompt(api_client, orgs.a.headers, "a-prompt")
    response = await api_client.delete(f"/api/v1/prompts/{prompt['id']}", headers=orgs.b.headers)
    assert response.status_code == 404


async def test_create_version_in_other_org_returns_404(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    prompt = await _create_prompt(api_client, orgs.a.headers, "a-prompt")
    response = await api_client.post(
        f"/api/v1/prompts/{prompt['id']}/versions",
        headers=orgs.b.headers,
        json={"body": "evil v2", "variables": []},
    )
    assert response.status_code == 404


async def test_get_version_in_other_org_returns_404(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    prompt = await _create_prompt(api_client, orgs.a.headers, "a-prompt")
    version_id = prompt["latest_version"]["id"]
    response = await api_client.get(f"/api/v1/versions/{version_id}", headers=orgs.b.headers)
    assert response.status_code == 404
