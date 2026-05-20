"""Shared pytest fixtures.

`isolate_env` runs autouse so tests never see ambient env vars that could leak from
the developer's shell. Tests opt in to specific env via the `base_env` fixture or by
setting vars via `monkeypatch`.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "PF_DATABASE_URL",
        "PF_JWT_SECRET",
        "PF_LOG_LEVEL",
        "PF_CORS_ORIGINS",
        "PF_OPENAI_API_KEY",
        "PF_ANTHROPIC_API_KEY",
        "PF_DEMO_EMAIL",
        "PF_DEMO_RATE_LIMIT",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimum env required for `Settings()` to load."""
    monkeypatch.setenv(
        "PF_DATABASE_URL",
        "postgresql+asyncpg://test:test@localhost:5432/test",
    )
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
