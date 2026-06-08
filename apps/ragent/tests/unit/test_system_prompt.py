"""Unit: system-prompt resolution → fetch → cache/fallback (DB + httpx mocked)."""

from typing import Any
from uuid import uuid4

import pytest
from jose import jwt

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.services import system_prompt as sp
from promptforge_ragent.services.platform import DemoPrincipal
from promptforge_ragent.services.system_prompt import (
    DEFAULT_SYSTEM_PROMPT,
    _service_token,
    get_system_prompt,
)

pytestmark = pytest.mark.usefixtures("base_env")


@pytest.fixture(autouse=True)
def _reset() -> None:
    sp._reset_cache()
    get_settings.cache_clear()


def _patch_resolution(
    monkeypatch: pytest.MonkeyPatch, principal: DemoPrincipal | None, version_id: object
) -> None:
    async def fake_principal(session: Any, slug: str) -> DemoPrincipal | None:
        return principal

    async def fake_version(session: Any, org_id: Any, name: str) -> object:
        return version_id

    monkeypatch.setattr(sp, "resolve_demo_principal", fake_principal)
    monkeypatch.setattr(sp, "resolve_prompt_version_id", fake_version)


async def test_default_when_org_not_seeded(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_resolution(monkeypatch, None, None)
    assert await get_system_prompt(None) == DEFAULT_SYSTEM_PROMPT  # type: ignore[arg-type]


async def test_default_when_prompt_not_seeded(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_resolution(monkeypatch, DemoPrincipal(uuid4(), uuid4()), None)
    assert await get_system_prompt(None) == DEFAULT_SYSTEM_PROMPT  # type: ignore[arg-type]


async def test_resolved_fetch_returns_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_resolution(monkeypatch, DemoPrincipal(uuid4(), uuid4()), uuid4())
    calls = {"n": 0}

    async def fake_fetch(base_url: str, version_id: str, token: str) -> str:
        calls["n"] += 1
        assert token  # a JWT was minted
        return "LIVE PROMPT"

    monkeypatch.setattr(sp, "_fetch_version_body", fake_fetch)
    assert await get_system_prompt(None) == "LIVE PROMPT"  # type: ignore[arg-type]
    assert await get_system_prompt(None) == "LIVE PROMPT"  # type: ignore[arg-type]
    assert calls["n"] == 1  # second served from cache


async def test_failed_fetch_falls_back_and_does_not_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolution(monkeypatch, DemoPrincipal(uuid4(), uuid4()), uuid4())
    calls = {"n": 0}

    async def boom(base_url: str, version_id: str, token: str) -> str:
        calls["n"] += 1
        raise RuntimeError("api down")

    monkeypatch.setattr(sp, "_fetch_version_body", boom)
    assert await get_system_prompt(None) == DEFAULT_SYSTEM_PROMPT  # type: ignore[arg-type]
    assert await get_system_prompt(None) == DEFAULT_SYSTEM_PROMPT  # type: ignore[arg-type]
    assert calls["n"] == 2  # failure isn't cached → retried


def test_service_token_mints_decodable_jwt() -> None:
    org_id, user_id = uuid4(), uuid4()
    token = _service_token(DemoPrincipal(org_id=org_id, user_id=user_id))
    claims = jwt.decode(token, "a" * 48, algorithms=["HS256"])
    assert claims["org"] == str(org_id)
    assert claims["sub"] == str(user_id)
    assert claims["typ"] == "access"
    assert claims["role"] == "member"
