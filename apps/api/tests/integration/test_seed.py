"""Integration test for the demo seed: idempotency + expected dataset."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.models import OrgRole, Prompt, User
from promptforge_api.seed import DEMO_ORG_SLUG, seed_demo

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

DEMO_EMAIL = "demo@promptforge.dev"


async def _clean_demo(session: AsyncSession) -> None:
    # Start from a known-empty demo slice — other tests may have committed demo
    # rows to the shared container (org delete cascades to all its children).
    from promptforge_api.models import Org

    await session.execute(delete(Org).where(Org.slug == DEMO_ORG_SLUG))
    await session.execute(delete(User).where(User.email == DEMO_EMAIL))
    await session.flush()


async def test_seed_demo_idempotent_and_populated(db_session: AsyncSession) -> None:
    await _clean_demo(db_session)

    first = await seed_demo(db_session)
    assert first == {"prompts": 3, "runs": 4, "eval_cases": 3, "eval_results": 3}

    # Running again changes nothing — get-or-create all the way down.
    second = await seed_demo(db_session)
    assert second == first

    # Demo account is wired for /demo/login (DEMO membership) and is unusable via
    # password login (hash exists but no plaintext was ever set to a known value).
    user = (await db_session.execute(select(User).where(User.email == DEMO_EMAIL))).scalar_one()
    assert any(m.role is OrgRole.DEMO for m in user.memberships)

    # The headline prompt got both versions.
    support = (
        await db_session.execute(select(Prompt).where(Prompt.name == "Support Reply Drafter"))
    ).scalar_one()
    assert {v.version for v in support.versions} == {1, 2}
