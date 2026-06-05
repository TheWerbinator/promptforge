"""Shared pytest fixtures.

`isolate_env` runs autouse so tests never see ambient `PF_*` vars leaking from
the developer's shell. `base_env` sets the minimum env for `Settings()` to load.
`get_settings` is lru_cached, so it's cleared around env-mutating tests.
"""

import pytest

from promptforge_ragent.core.config import get_settings


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "PF_DATABASE_URL",
        "PF_JWT_SECRET",
        "PF_API_BASE_URL",
        "PF_LOG_LEVEL",
        "PF_CORS_ORIGINS",
        "PF_OPENAI_API_KEY",
        "PF_ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimum env required for `Settings()` to load."""
    monkeypatch.setenv(
        "PF_DATABASE_URL",
        "postgresql+asyncpg://test:test@localhost:5432/test",
    )
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()
