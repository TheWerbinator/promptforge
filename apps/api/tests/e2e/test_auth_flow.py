"""End-to-end HTTP tests for the auth flow.

Uses `api_client` from `tests/e2e/conftest.py`: a real ASGI app + real Postgres
via testcontainers with truncate-between-tests isolation.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from promptforge_api.api.v1.auth import REFRESH_COOKIE

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


SIGNUP_BODY = {
    "email": "jake@example.com",
    "password": "Sup3rSecret!",
    "display_name": "Jake",
}


async def test_signup_creates_user_org_membership_and_session(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["user"]["email"] == "jake@example.com"
    assert data["org"]["slug"].startswith("jake")
    assert data["role"] == "owner"
    assert data["access_token"]
    assert REFRESH_COOKIE in response.cookies


async def test_duplicate_signup_returns_409(api_client: AsyncClient) -> None:
    first = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    assert first.status_code == 201
    second = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    assert second.status_code == 409


async def test_login_with_correct_password(api_client: AsyncClient) -> None:
    await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "jake@example.com", "password": "Sup3rSecret!"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_wrong_password_returns_401(api_client: AsyncClient) -> None:
    await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "jake@example.com", "password": "wrong"},
    )
    assert response.status_code == 401


async def test_me_endpoint_requires_token(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_endpoint_returns_user(api_client: AsyncClient) -> None:
    signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    token = signup.json()["access_token"]
    response = await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "jake@example.com"
    assert data["role"] == "owner"
    assert len(data["memberships"]) == 1


async def test_refresh_rotates_cookie_and_issues_new_access(
    api_client: AsyncClient,
) -> None:
    signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    original_cookie = signup.cookies[REFRESH_COOKIE]

    refresh = await api_client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 200
    new_cookie = refresh.cookies.get(REFRESH_COOKIE)
    assert new_cookie is not None
    assert new_cookie != original_cookie
    assert refresh.json()["access_token"]


async def test_refresh_replay_revokes_chain(api_client: AsyncClient) -> None:
    signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    original_cookie = signup.cookies[REFRESH_COOKIE]

    # First rotation succeeds and replaces original.
    first_refresh = await api_client.post("/api/v1/auth/refresh")
    assert first_refresh.status_code == 200
    new_cookie = first_refresh.cookies[REFRESH_COOKIE]

    # Replay the original (already-rotated) cookie. Pass via cookies= on the request
    # so we sidestep the persistent client jar entirely.
    api_client.cookies.clear()
    replay = await api_client.post(
        "/api/v1/auth/refresh", cookies={REFRESH_COOKIE: original_cookie}
    )
    assert replay.status_code == 401
    assert "replay" in replay.json()["detail"].lower()

    # Chain is revoked: even the latest token can no longer refresh.
    after_revoke = await api_client.post(
        "/api/v1/auth/refresh", cookies={REFRESH_COOKIE: new_cookie}
    )
    assert after_revoke.status_code == 401


async def test_logout_clears_cookie_and_revokes(api_client: AsyncClient) -> None:
    await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    logout = await api_client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    # Subsequent refresh must fail (cookie cleared on server response too).
    refresh = await api_client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 401


async def test_api_key_create_and_authenticate(api_client: AsyncClient) -> None:
    signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    token = signup.json()["access_token"]

    create = await api_client.post(
        "/api/v1/auth/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "ci"},
    )
    assert create.status_code == 201
    key = create.json()["key"]
    assert key.startswith("pf_live_")

    me_via_key = await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {key}"})
    assert me_via_key.status_code == 200
    assert me_via_key.json()["user"]["email"] == "jake@example.com"


async def test_api_key_cannot_create_another_api_key(api_client: AsyncClient) -> None:
    signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    token = signup.json()["access_token"]
    create = await api_client.post(
        "/api/v1/auth/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "first"},
    )
    key = create.json()["key"]

    # API key auth should not be allowed to mint more keys.
    second = await api_client.post(
        "/api/v1/auth/api-keys",
        headers={"Authorization": f"Bearer {key}"},
        json={"name": "second"},
    )
    assert second.status_code == 403


async def test_refresh_with_no_cookie_returns_401(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()


async def test_refresh_with_unknown_token_returns_401(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/auth/refresh", cookies={REFRESH_COOKIE: "not-a-real-token"}
    )
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


async def test_me_with_garbage_token_returns_401(api_client: AsyncClient) -> None:
    response = await api_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer garbage-token"}
    )
    assert response.status_code == 401


async def test_me_with_unknown_api_key_returns_401(api_client: AsyncClient) -> None:
    fake = "pf_live_abcd1234_" + "x" * 40
    response = await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {fake}"})
    assert response.status_code == 401


async def test_api_key_list_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/auth/api-keys")
    assert response.status_code == 401


async def test_logout_without_cookie_is_idempotent(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/auth/logout")
    assert response.status_code == 204


async def test_api_key_revoke_other_org_returns_404(api_client: AsyncClient) -> None:
    """Issuing a key for org A then attempting to revoke under org B yields 404."""
    # Org A
    signup_a = await api_client.post(
        "/api/v1/auth/signup",
        json={"email": "a@example.com", "password": "Sup3rSecret!"},
    )
    token_a = signup_a.json()["access_token"]
    create = await api_client.post(
        "/api/v1/auth/api-keys",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "a"},
    )
    key_id = create.json()["id"]

    # Org B
    api_client.cookies.clear()
    signup_b = await api_client.post(
        "/api/v1/auth/signup",
        json={"email": "b@example.com", "password": "Sup3rSecret!"},
    )
    token_b = signup_b.json()["access_token"]

    revoke = await api_client.delete(
        f"/api/v1/auth/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert revoke.status_code == 404


async def test_api_key_list_and_revoke(api_client: AsyncClient) -> None:
    signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    token = signup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = await api_client.post("/api/v1/auth/api-keys", headers=headers, json={"name": "first"})
    key_id = create.json()["id"]

    listed = await api_client.get("/api/v1/auth/api-keys", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    revoke = await api_client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=headers)
    assert revoke.status_code == 204

    listed_after = await api_client.get("/api/v1/auth/api-keys", headers=headers)
    assert listed_after.json() == []
