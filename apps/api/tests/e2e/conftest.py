"""Shared fixtures for e2e tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from promptforge_api.core.db import dispose_engine


@pytest_asyncio.fixture
async def api_client(
    pg_url: str,
    _migrated_engine: None,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("PF_DATABASE_URL", pg_url)
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    monkeypatch.setenv("PF_COOKIE_SECURE", "false")

    from promptforge_api.core.config import get_settings

    get_settings.cache_clear()

    cleanup_engine = create_async_engine(pg_url, future=True)
    truncate_sql = (
        "TRUNCATE refresh_tokens, api_keys, memberships, orgs, users RESTART IDENTITY CASCADE"
    )
    async with cleanup_engine.begin() as conn:
        await conn.execute(text(truncate_sql))
    await cleanup_engine.dispose()

    await dispose_engine()

    from promptforge_api.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    await dispose_engine()
