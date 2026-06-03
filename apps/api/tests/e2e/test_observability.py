"""E2E for the request-context middleware: X-Request-ID is always set + echoed."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def test_response_carries_a_request_id(api_client: AsyncClient) -> None:
    r = await api_client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("x-request-id"), "every response should carry a request id"


async def test_incoming_request_id_is_echoed(api_client: AsyncClient) -> None:
    rid = "trace-correlation-abc123"
    r = await api_client.get("/health", headers={"X-Request-ID": rid})
    assert r.headers.get("x-request-id") == rid


async def test_request_id_set_on_error_responses(api_client: AsyncClient) -> None:
    # 401 path still goes through the outermost middleware.
    r = await api_client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.headers.get("x-request-id")
