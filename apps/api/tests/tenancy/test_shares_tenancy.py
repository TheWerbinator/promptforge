"""Tenancy contract for ShareToken: list-excludes + revoke-404 across orgs."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.tenancy._helpers import make_two_orgs

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def _create_prompt_and_share(client: AsyncClient, headers: dict[str, str]) -> str:
    prompt = await client.post(
        "/api/v1/prompts",
        headers=headers,
        json={"name": "p", "body": "x", "variables": []},
    )
    assert prompt.status_code == 201, prompt.text
    share = await client.post(
        "/api/v1/shares",
        headers=headers,
        json={"resource_type": "prompt", "resource_id": prompt.json()["id"]},
    )
    assert share.status_code == 201, share.text
    return str(share.json()["id"])


async def test_list_excludes_other_orgs_shares(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    await _create_prompt_and_share(api_client, orgs.a.headers)

    response = await api_client.get("/api/v1/shares", headers=orgs.b.headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_revoke_other_orgs_share_returns_404(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    share_id = await _create_prompt_and_share(api_client, orgs.a.headers)

    response = await api_client.delete(f"/api/v1/shares/{share_id}", headers=orgs.b.headers)
    assert response.status_code == 404


async def test_owner_can_list_and_revoke_own_share(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    share_id = await _create_prompt_and_share(api_client, orgs.a.headers)

    listed = await api_client.get("/api/v1/shares", headers=orgs.a.headers)
    assert listed.status_code == 200
    assert any(s["id"] == share_id for s in listed.json())

    revoked = await api_client.delete(f"/api/v1/shares/{share_id}", headers=orgs.a.headers)
    assert revoked.status_code == 204
