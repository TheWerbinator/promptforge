"""Integration: demo-entity resolution + system-prompt fetch against real DB stubs."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.services import system_prompt as sp
from promptforge_ragent.services.platform import (
    resolve_demo_principal,
    resolve_prompt_version_id,
)
from promptforge_ragent.services.system_prompt import get_system_prompt

pytestmark = pytest.mark.integration


async def _seed_api_entities(session: AsyncSession) -> tuple[object, object, object]:
    org_id, user_id, prompt_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    await session.execute(
        text("INSERT INTO orgs (id, slug, name) VALUES (:id, 'demo-corp', 'Demo Corp')"),
        {"id": org_id},
    )
    await session.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": user_id})
    await session.execute(
        text("INSERT INTO memberships (user_id, org_id) VALUES (:u, :o)"),
        {"u": user_id, "o": org_id},
    )
    await session.execute(
        text("INSERT INTO prompts (id, org_id, name) VALUES (:id, :o, 'RAG Agent System Prompt')"),
        {"id": prompt_id, "o": org_id},
    )
    # Two versions — the resolver must return the latest.
    await session.execute(
        text("INSERT INTO prompt_versions (id, prompt_id, version, body) VALUES (:i, :p, 1, 'v1')"),
        {"i": uuid4(), "p": prompt_id},
    )
    await session.execute(
        text("INSERT INTO prompt_versions (id, prompt_id, version, body) VALUES (:i, :p, 2, 'v2')"),
        {"i": version_id, "p": prompt_id},
    )
    return org_id, user_id, version_id


async def test_resolve_demo_principal_and_version(db_session: AsyncSession) -> None:
    org_id, user_id, version_id = await _seed_api_entities(db_session)

    principal = await resolve_demo_principal(db_session, "demo-corp")
    assert principal is not None
    assert principal.org_id == org_id
    assert principal.user_id == user_id

    resolved = await resolve_prompt_version_id(db_session, org_id, "RAG Agent System Prompt")
    assert resolved == version_id  # latest version


async def test_resolve_missing_org_returns_none(db_session: AsyncSession) -> None:
    assert await resolve_demo_principal(db_session, "nope") is None


async def test_get_system_prompt_resolves_then_fetches(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PF_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()
    sp._reset_cache()

    _, _, version_id = await _seed_api_entities(db_session)
    captured: dict[str, object] = {}

    async def fake_fetch(base_url: str, vid: str, token: str) -> str:
        captured["version_id"] = vid
        return "RESOLVED BODY"

    monkeypatch.setattr(sp, "_fetch_version_body", fake_fetch)

    assert await get_system_prompt(db_session) == "RESOLVED BODY"
    assert captured["version_id"] == str(version_id)  # resolved the latest version
