"""E2E: demo free-turn quota (per-IP + global) → BYOK/402."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from promptforge_ragent.agent import loop as loop_module
from promptforge_ragent.core.config import get_settings

pytestmark = pytest.mark.e2e

_SECRET = "a" * 48


def _token(user_id: UUID, org_id: UUID, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "role": role,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def _mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        # No tool calls → the agent answers immediately (one turn, no retrieval).
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None))]
        )

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)


async def _seed(factory: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    async with factory() as session:
        org_id, user_id = uuid4(), uuid4()
        await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
        await session.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": user_id})
        await session.execute(
            text(
                "INSERT INTO corpora (id, org_id, slug, name, embedding_model, created_at, "
                "updated_at) VALUES (gen_random_uuid(), :o, 'docs', 'Docs', "
                "'openai_text_embedding_3_small', now(), now())"
            ),
            {"o": org_id},
        )
        await session.commit()
    return org_id, user_id


def _set_caps(monkeypatch: pytest.MonkeyPatch, *, per_ip: int, glob: int) -> None:
    monkeypatch.setenv("PF_DEMO_FREE_TURNS_PER_IP", str(per_ip))
    monkeypatch.setenv("PF_DEMO_FREE_TURNS_GLOBAL", str(glob))
    get_settings.cache_clear()


async def _chat(client: AsyncClient, token: str, *, ip: str = "1.2.3.4", byok: bool = False) -> int:
    headers = {"Authorization": f"Bearer {token}", "Fly-Client-IP": ip}
    if byok:
        headers["X-Provider-Key"] = "sk-user-key"
    resp = await client.post(
        "/api/v1/chat", json={"message": "hello", "corpus_slug": "docs"}, headers=headers
    )
    return resp.status_code


async def test_demo_free_turns_then_402(
    app_client: AsyncClient,
    committed_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_llm(monkeypatch)
    org_id, user_id = await _seed(committed_db)
    _set_caps(monkeypatch, per_ip=2, glob=100)
    token = _token(user_id, org_id, "demo")

    assert await _chat(app_client, token) == 200  # turn 1
    assert await _chat(app_client, token) == 200  # turn 2
    assert await _chat(app_client, token) == 402  # exhausted per-IP


async def test_demo_byok_skips_quota(
    app_client: AsyncClient,
    committed_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_llm(monkeypatch)
    org_id, user_id = await _seed(committed_db)
    _set_caps(monkeypatch, per_ip=0, glob=0)  # no free turns at all
    token = _token(user_id, org_id, "demo")

    assert await _chat(app_client, token, byok=True) == 200  # BYOK bypasses the quota


async def test_global_cap_stops_ip_rotation(
    app_client: AsyncClient,
    committed_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_llm(monkeypatch)
    org_id, user_id = await _seed(committed_db)
    _set_caps(monkeypatch, per_ip=100, glob=1)  # generous per-IP, tiny global
    token = _token(user_id, org_id, "demo")

    assert await _chat(app_client, token, ip="1.1.1.1") == 200  # consumes the global pool
    assert await _chat(app_client, token, ip="2.2.2.2") == 402  # different IP, global exhausted


async def test_member_is_not_quota_limited(
    app_client: AsyncClient,
    committed_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_llm(monkeypatch)
    org_id, user_id = await _seed(committed_db)
    _set_caps(monkeypatch, per_ip=0, glob=0)
    token = _token(user_id, org_id, "member")
    assert await _chat(app_client, token) == 200  # non-demo always uses the hosted key
