"""Shared helpers for tenancy contract tests.

A `TwoOrgs` object holds two independently-signed-in users in distinct orgs.
Each tenancy test file calls `make_two_orgs(api_client)` once, then exercises
the cross-org access matrix on its specific resource.
"""

from __future__ import annotations

from dataclasses import dataclass

from httpx import AsyncClient


@dataclass(frozen=True)
class OrgUser:
    email: str
    access_token: str
    user_id: str
    org_id: str
    org_slug: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


@dataclass(frozen=True)
class TwoOrgs:
    a: OrgUser
    b: OrgUser


async def make_two_orgs(api_client: AsyncClient) -> TwoOrgs:
    """Sign up two distinct users in two distinct orgs. The api_client cookie
    jar holds the last user's refresh cookie; tests that don't care can ignore
    it, but anything that uses /auth/refresh should clear the jar first."""

    async def _signup(email: str) -> OrgUser:
        response = await api_client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "Sup3rSecret!"},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        return OrgUser(
            email=email,
            access_token=data["access_token"],
            user_id=data["user"]["id"],
            org_id=data["org"]["id"],
            org_slug=data["org"]["slug"],
        )

    a = await _signup("tenant-a@example.com")
    api_client.cookies.clear()
    b = await _signup("tenant-b@example.com")
    api_client.cookies.clear()
    return TwoOrgs(a=a, b=b)
