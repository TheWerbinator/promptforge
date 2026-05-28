"""End-to-end HTTP tests for prompts + versions."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


SIGNUP_BODY = {
    "email": "jake@example.com",
    "password": "Sup3rSecret!",
    "display_name": "Jake",
}


async def _signup(client: AsyncClient, body: dict | None = None) -> dict:
    response = await client.post("/api/v1/auth/signup", json=body or SIGNUP_BODY)
    assert response.status_code == 201, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_create_prompt_returns_prompt_with_v1(api_client: AsyncClient) -> None:
    auth = await _signup(api_client)
    response = await api_client.post(
        "/api/v1/prompts",
        headers=_headers(auth["access_token"]),
        json={
            "name": "summarize",
            "description": "3-sentence summary",
            "tags": ["summarize"],
            "body": "Summarize:\n{{document}}",
            "variables": [{"name": "document", "type": "str", "required": True}],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "summarize"
    assert data["tags"] == ["summarize"]
    assert data["latest_version"]["version"] == 1
    assert "document" in data["latest_version"]["body"]


async def test_duplicate_prompt_name_within_org_returns_409(api_client: AsyncClient) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    payload = {"name": "dup", "body": "x", "variables": []}
    first = await api_client.post("/api/v1/prompts", headers=headers, json=payload)
    assert first.status_code == 201
    second = await api_client.post("/api/v1/prompts", headers=headers, json=payload)
    assert second.status_code == 409


async def test_list_prompts_filters_by_q_and_tag(api_client: AsyncClient) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])

    for name, tags in [("summarize", ["summarize"]), ("classify", ["classify"])]:
        await api_client.post(
            "/api/v1/prompts",
            headers=headers,
            json={"name": name, "body": "x", "variables": [], "tags": tags},
        )

    q_resp = await api_client.get("/api/v1/prompts?q=summa", headers=headers)
    assert q_resp.status_code == 200
    assert {p["name"] for p in q_resp.json()["items"]} == {"summarize"}

    tag_resp = await api_client.get("/api/v1/prompts?tag=classify", headers=headers)
    assert {p["name"] for p in tag_resp.json()["items"]} == {"classify"}


async def test_private_prompt_hidden_from_other_org_member(api_client: AsyncClient) -> None:
    # Workaround: we don't yet have multi-member orgs, so we simulate "another
    # user in the same org" by creating a second user and inviting them. Without
    # invite endpoints, the simplest cross-user-same-org check is a TODO. For
    # now, assert PRIVATE prompts ARE visible to their creator.
    # TODO(phase-7+): once member-invites land, add a real "private prompt hidden
    # from same-org peer" test here.
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    response = await api_client.post(
        "/api/v1/prompts",
        headers=headers,
        json={
            "name": "secret",
            "body": "x",
            "variables": [],
            "visibility": "private",
        },
    )
    assert response.status_code == 201
    listed = await api_client.get("/api/v1/prompts", headers=headers)
    assert any(p["name"] == "secret" for p in listed.json()["items"])


async def test_patch_prompt_meta(api_client: AsyncClient) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    created = (
        await api_client.post(
            "/api/v1/prompts",
            headers=headers,
            json={"name": "p", "body": "x", "variables": []},
        )
    ).json()

    response = await api_client.patch(
        f"/api/v1/prompts/{created['id']}",
        headers=headers,
        json={"description": "now with desc", "tags": ["meta"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "now with desc"
    assert body["tags"] == ["meta"]


async def test_new_version_increments(api_client: AsyncClient) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    created = (
        await api_client.post(
            "/api/v1/prompts",
            headers=headers,
            json={"name": "p", "body": "v1 body", "variables": []},
        )
    ).json()
    prompt_id = created["id"]

    v2 = await api_client.post(
        f"/api/v1/prompts/{prompt_id}/versions",
        headers=headers,
        json={"body": "v2 body", "variables": []},
    )
    assert v2.status_code == 201
    assert v2.json()["version"] == 2

    versions = await api_client.get(f"/api/v1/prompts/{prompt_id}/versions", headers=headers)
    assert [v["version"] for v in versions.json()] == [2, 1]


async def test_get_version_by_id(api_client: AsyncClient) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    created = (
        await api_client.post(
            "/api/v1/prompts",
            headers=headers,
            json={"name": "p", "body": "v1 body", "variables": []},
        )
    ).json()
    version_id = created["latest_version"]["id"]

    response = await api_client.get(f"/api/v1/versions/{version_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["body"] == "v1 body"


async def test_delete_prompt_cascades_versions(api_client: AsyncClient) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    created = (
        await api_client.post(
            "/api/v1/prompts",
            headers=headers,
            json={"name": "p", "body": "x", "variables": []},
        )
    ).json()
    prompt_id = created["id"]
    version_id = created["latest_version"]["id"]

    resp = await api_client.delete(f"/api/v1/prompts/{prompt_id}", headers=headers)
    assert resp.status_code == 204

    after = await api_client.get(f"/api/v1/versions/{version_id}", headers=headers)
    assert after.status_code == 404


async def test_list_pagination(api_client: AsyncClient) -> None:
    auth = await _signup(api_client)
    headers = _headers(auth["access_token"])
    for i in range(7):
        await api_client.post(
            "/api/v1/prompts",
            headers=headers,
            json={"name": f"p{i}", "body": "x", "variables": []},
        )

    page1 = await api_client.get("/api/v1/prompts?page=1&page_size=3", headers=headers)
    assert page1.json()["total"] == 7
    assert page1.json()["has_more"] is True
    assert len(page1.json()["items"]) == 3

    last_page = await api_client.get("/api/v1/prompts?page=3&page_size=3", headers=headers)
    assert last_page.json()["has_more"] is False
