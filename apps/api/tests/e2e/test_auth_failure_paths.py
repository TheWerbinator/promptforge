"""Failure-path coverage for auth endpoints.

These tests poke the DB directly (or use freezegun) to drive defensive branches
that the happy-path e2e tests cannot reach: expired tokens, deactivated users,
removed memberships, users with zero memberships, and double-revocation of
API keys.
"""

from __future__ import annotations

import pytest
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from promptforge_api.api.v1.auth import REFRESH_COOKIE
from promptforge_api.core.security import hash_password

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


SIGNUP_BODY = {
  "email": "shawn@example.com",
  "password": "Sup3rSecret!",
  "display_name": "Shawn",
}


async def test_refresh_with_expired_token_returns_401(api_client: AsyncClient) -> None:
  """Signing up far in the past makes the refresh-token's stored expires_at
  sit in the real past. After freezegun exits the refresh handler trips the
  expiry branch."""
  with freeze_time("2020-01-01 00:00:00"):
    signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
    assert signup.status_code == 201
    original_cookie = signup.cookies[REFRESH_COOKIE]

  api_client.cookies.clear()
  response = await api_client.post(
    "/api/v1/auth/refresh", cookies={REFRESH_COOKIE: original_cookie}
  )
  assert response.status_code == 401
  assert "expired" in response.json()["detail"].lower()


async def test_refresh_after_user_deactivated_returns_401(
  api_client: AsyncClient, pg_url: str
) -> None:
  signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
  user_id = signup.json()["user"]["id"]

  engine = create_async_engine(pg_url, future=True)
  async with engine.begin() as conn:
    await conn.execute(
      text("UPDATE users SET is_active = false WHERE id = CAST(:uid AS uuid)"),
      {"uid": user_id},
    )
  await engine.dispose()

  response = await api_client.post("/api/v1/auth/refresh")
  assert response.status_code == 401
  assert "unavailable" in response.json()["detail"].lower()


async def test_refresh_after_membership_removed_returns_401(
  api_client: AsyncClient, pg_url: str
) -> None:
  signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
  user_id = signup.json()["user"]["id"]

  engine = create_async_engine(pg_url, future=True)
  async with engine.begin() as conn:
    await conn.execute(
      text("DELETE FROM memberships WHERE user_id = CAST(:uid AS uuid)"),
      {"uid": user_id},
    )
  await engine.dispose()

  response = await api_client.post("/api/v1/auth/refresh")
  assert response.status_code == 401
  assert "membership" in response.json()["detail"].lower()


async def test_login_user_without_membership_returns_403(
  api_client: AsyncClient, pg_url: str
) -> None:
  """A user inserted via raw SQL with no Membership row cannot log in."""
  engine = create_async_engine(pg_url, future=True)
  async with engine.begin() as conn:
    await conn.execute(
      text(
        "INSERT INTO users (id, email, password_hash, is_active, "
        "created_at, updated_at) VALUES "
        "(gen_random_uuid(), :email, :pwd, true, now(), now())"
      ),
      {"email": "lonely@example.com", "pwd": hash_password("Sup3rSecret!")},
    )
  await engine.dispose()

  response = await api_client.post(
    "/api/v1/auth/login",
    json={"email": "lonely@example.com", "password": "Sup3rSecret!"},
  )
  assert response.status_code == 403
  assert "membership" in response.json()["detail"].lower()


async def test_revoke_already_revoked_api_key_returns_404(api_client: AsyncClient) -> None:
  signup = await api_client.post("/api/v1/auth/signup", json=SIGNUP_BODY)
  token = signup.json()["access_token"]
  headers = {"Authorization": f"Bearer {token}"}

  create = await api_client.post("/api/v1/auth/api-keys", headers=headers, json={"name": "ci"})
  key_id = create.json()["id"]

  first = await api_client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=headers)
  assert first.status_code == 204

  second = await api_client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=headers)
  assert second.status_code == 404


async def test_signup_with_cjk_only_org_name_uses_fallback_slug(
  api_client: AsyncClient,
) -> None:
  """Non-ASCII-only input strips to empty in the slugifier; covers the
  `or 'org'` fallback branch."""
  response = await api_client.post(
    "/api/v1/auth/signup",
    json={
      "email": "user@example.com",
      "password": "Sup3rSecret!",
      "org_name": "日本語",
    },
  )
  assert response.status_code == 201
  assert response.json()["org"]["slug"].startswith("org")


async def test_logout_clears_cookie_idempotently_when_token_unknown(
  api_client: AsyncClient,
) -> None:
  """Logout with a bogus cookie value should still 204 and not raise."""
  response = await api_client.post("/api/v1/auth/logout", cookies={REFRESH_COOKIE: "bogus"})
  assert response.status_code == 204
