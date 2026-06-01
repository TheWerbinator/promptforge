"""Integration tests for the Run model itself."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.models import Org, Prompt, PromptVersion, Run, User

pytestmark = pytest.mark.integration


async def _seed(session: AsyncSession, *, email: str, slug: str) -> tuple[User, Org, PromptVersion]:
    user = User(email=email, password_hash="x" * 64)
    org = Org(name="Acme", slug=slug)
    session.add_all([user, org])
    await session.flush()
    prompt = Prompt(org_id=org.id, name="p", tags=[], created_by=user.id)
    session.add(prompt)
    await session.flush()
    version = PromptVersion(prompt_id=prompt.id, version=1, body="hi", variables=[])
    session.add(version)
    await session.flush()
    return user, org, version


async def test_run_insert_with_cost_precision(db_session: AsyncSession) -> None:
    user, org, version = await _seed(db_session, email="a@example.com", slug="run-a")
    run = Run(
        org_id=org.id,
        version_id=version.id,
        model="openai/gpt-4o-mini",
        inputs={"x": 1},
        output="hello",
        input_tokens=10,
        output_tokens=3,
        cost_usd=Decimal("0.000123"),
        latency_ms=42,
        created_by=user.id,
    )
    db_session.add(run)
    await db_session.flush()

    fetched = (await db_session.execute(select(Run).where(Run.id == run.id))).scalar_one()
    assert fetched.cost_usd == Decimal("0.000123")
    assert fetched.inputs == {"x": 1}
    assert fetched.output == "hello"


async def test_run_persists_with_error_and_null_cost(db_session: AsyncSession) -> None:
    _, org, version = await _seed(db_session, email="b@example.com", slug="run-b")
    run = Run(
        org_id=org.id,
        version_id=version.id,
        model="custom/local",
        inputs={},
        output=None,
        cost_usd=None,
        latency_ms=0,
        error="provider down",
    )
    db_session.add(run)
    await db_session.flush()

    fetched = (await db_session.execute(select(Run).where(Run.id == run.id))).scalar_one()
    assert fetched.output is None
    assert fetched.cost_usd is None
    assert fetched.error == "provider down"


async def test_deleting_version_cascades_to_runs(db_session: AsyncSession) -> None:
    _, org, version = await _seed(db_session, email="c@example.com", slug="run-c")
    db_session.add(
        Run(
            org_id=org.id,
            version_id=version.id,
            model="openai/gpt-4o-mini",
            inputs={},
        )
    )
    await db_session.flush()

    await db_session.delete(version)
    await db_session.flush()
    remaining = (await db_session.execute(select(Run).where(Run.version_id == version.id))).first()
    assert remaining is None
