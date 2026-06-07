"""Unit: system-prompt fetch (default / live / cache / failure) + service token."""

import pytest
from jose import jwt

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.services import system_prompt as sp
from promptforge_ragent.services.system_prompt import (
    DEFAULT_SYSTEM_PROMPT,
    _service_token,
    get_system_prompt,
)


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PF_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)


def _configure_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("PF_SYSTEM_PROMPT_VERSION_ID", "ver-123")
    monkeypatch.setenv("PF_SERVICE_ORG_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("PF_SERVICE_USER_ID", "22222222-2222-2222-2222-222222222222")


@pytest.fixture(autouse=True)
def _reset() -> None:
    sp._reset_cache()
    get_settings.cache_clear()


async def test_default_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    get_settings.cache_clear()
    assert await get_system_prompt() == DEFAULT_SYSTEM_PROMPT


async def test_live_fetch_returns_and_caches_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_fetch(monkeypatch)
    get_settings.cache_clear()
    calls = {"n": 0}

    async def fake_fetch(base_url: str, version_id: str, token: str) -> str:
        calls["n"] += 1
        assert version_id == "ver-123"
        assert token  # a JWT was minted
        return "LIVE SYSTEM PROMPT"

    monkeypatch.setattr(sp, "_fetch_version_body", fake_fetch)

    assert await get_system_prompt() == "LIVE SYSTEM PROMPT"
    assert await get_system_prompt() == "LIVE SYSTEM PROMPT"
    assert calls["n"] == 1  # second call served from cache


async def test_failed_fetch_falls_back_and_does_not_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_fetch(monkeypatch)
    get_settings.cache_clear()
    calls = {"n": 0}

    async def boom(base_url: str, version_id: str, token: str) -> str:
        calls["n"] += 1
        raise RuntimeError("api down")

    monkeypatch.setattr(sp, "_fetch_version_body", boom)

    assert await get_system_prompt() == DEFAULT_SYSTEM_PROMPT
    assert await get_system_prompt() == DEFAULT_SYSTEM_PROMPT
    assert calls["n"] == 2  # failure is not cached → retried


def test_service_token_mints_decodable_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_fetch(monkeypatch)
    get_settings.cache_clear()
    token = _service_token(get_settings())
    assert token is not None
    claims = jwt.decode(token, "a" * 48, algorithms=["HS256"])
    assert claims["org"] == "11111111-1111-1111-1111-111111111111"
    assert claims["sub"] == "22222222-2222-2222-2222-222222222222"
    assert claims["typ"] == "access"
    assert claims["role"] == "member"


def test_service_token_none_when_principal_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    get_settings.cache_clear()
    assert _service_token(get_settings()) is None
