"""Tenancy contract for ApiKey.

Resources created in org A must be invisible (404 / list-excluded) to org B.
The contract here is the template later resources (Prompt, Run, EvalSuite, ...)
will reuse: list-excludes, get-404, modify-404, delete-404.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.tenancy._helpers import make_two_orgs

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def _create_key(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    response = await client.post("/api/v1/auth/api-keys", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_list_excludes_other_orgs_api_keys(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    await _create_key(api_client, orgs.a.headers, "a-key")

    response = await api_client.get("/api/v1/auth/api-keys", headers=orgs.b.headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_delete_other_orgs_api_key_returns_404(api_client: AsyncClient) -> None:
    orgs = await make_two_orgs(api_client)
    key_id = await _create_key(api_client, orgs.a.headers, "a-key")

    response = await api_client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=orgs.b.headers)
    assert response.status_code == 404


async def test_owners_can_still_see_and_revoke_own_keys(api_client: AsyncClient) -> None:
    """Sanity: the cross-org guards do not block the legitimate owner."""
    orgs = await make_two_orgs(api_client)
    key_id = await _create_key(api_client, orgs.a.headers, "a-key")

    listed = await api_client.get("/api/v1/auth/api-keys", headers=orgs.a.headers)
    assert listed.status_code == 200
    assert any(k["id"] == key_id for k in listed.json())

    revoked = await api_client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=orgs.a.headers)
    assert revoked.status_code == 204
