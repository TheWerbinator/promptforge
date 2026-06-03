"""E2E: the seed closes the loop — /demo/login works and the seeded public
share links resolve, end to end through the real app."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from promptforge_api.core.db import get_session_factory
from promptforge_api.seed import (
    DEMO_EVAL_SHARE_TOKEN,
    DEMO_PROMPT_SHARE_TOKEN,
    seed_demo,
)

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def _run_seed() -> None:
    async with get_session_factory()() as session:
        await seed_demo(session)
        await session.commit()


async def test_seed_enables_demo_login_and_public_shares(api_client: AsyncClient) -> None:
    await _run_seed()

    login = await api_client.post("/api/v1/demo/login")
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "demo"
    assert login.json()["org"]["slug"] == "demo-corp"

    prompt_share = await api_client.get(f"/api/v1/public/share/{DEMO_PROMPT_SHARE_TOKEN}")
    assert prompt_share.status_code == 200, prompt_share.text
    assert prompt_share.json()["resource_type"] == "prompt"
    assert prompt_share.json()["prompt"]["name"] == "Support Reply Drafter"

    eval_share = await api_client.get(f"/api/v1/public/share/{DEMO_EVAL_SHARE_TOKEN}")
    assert eval_share.status_code == 200, eval_share.text
    report = eval_share.json()["eval_batch"]
    assert report["status"] == "done"
    assert report["pass_rate"] == pytest.approx(2 / 3)
    assert len(report["results"]) == 3


async def test_seed_is_safe_to_run_twice(api_client: AsyncClient) -> None:
    await _run_seed()
    await _run_seed()  # must not raise (unique constraints, dupes)

    login = await api_client.post("/api/v1/demo/login")
    assert login.status_code == 200
