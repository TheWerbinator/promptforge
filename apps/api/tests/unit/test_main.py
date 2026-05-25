"""Unit tests for the FastAPI app factory and middleware wiring."""

from __future__ import annotations

import pytest
from fastapi.middleware.cors import CORSMiddleware

from promptforge_api.core.config import get_settings


def test_cors_middleware_installed_when_origins_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PF_DATABASE_URL", "postgresql+asyncpg://x:x@localhost:5432/x")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    monkeypatch.setenv("PF_CORS_ORIGINS", '["http://example.com"]')
    get_settings.cache_clear()

    from promptforge_api.main import create_app

    app = create_app()
    assert any(m.cls is CORSMiddleware for m in app.user_middleware)


def test_cors_middleware_skipped_when_origins_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PF_DATABASE_URL", "postgresql+asyncpg://x:x@localhost:5432/x")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    monkeypatch.delenv("PF_CORS_ORIGINS", raising=False)
    get_settings.cache_clear()

    from promptforge_api.main import create_app

    app = create_app()
    assert not any(m.cls is CORSMiddleware for m in app.user_middleware)
