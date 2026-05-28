"""Integration tests for Prompt + PromptVersion against real Postgres."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.models import (
    Org,
    Prompt,
    PromptVersion,
    PromptVisibility,
    User,
)

pytestmark = pytest.mark.integration


async def _seed_user_org(
    session: AsyncSession, *, email: str = "u@example.com", slug: str = "acme"
) -> tuple[User, Org]:
    user = User(email=email, password_hash="x" * 64)
    org = Org(name="Acme", slug=slug)
    session.add_all([user, org])
    await session.flush()
    return user, org


async def test_prompt_round_trip_with_version(db_session: AsyncSession) -> None:
    user, org = await _seed_user_org(db_session, email="a@example.com", slug="rt-a")
    prompt = Prompt(
        org_id=org.id,
        name="summarize",
        description="3-sentence summary",
        tags=["summarize"],
        visibility=PromptVisibility.ORG,
        created_by=user.id,
    )
    db_session.add(prompt)
    await db_session.flush()
    db_session.add(
        PromptVersion(
            prompt_id=prompt.id,
            version=1,
            body="Summarize:\n{{document}}",
            variables=[{"name": "document", "type": "str", "required": True}],
            created_by=user.id,
        )
    )
    await db_session.flush()

    fetched = (await db_session.execute(select(Prompt).where(Prompt.id == prompt.id))).scalar_one()
    assert fetched.tags == ["summarize"]
    assert fetched.visibility is PromptVisibility.ORG
    assert len(fetched.versions) == 1
    assert fetched.versions[0].body.startswith("Summarize")


async def test_prompt_name_unique_per_org(db_session: AsyncSession) -> None:
    _, org = await _seed_user_org(db_session, email="b@example.com", slug="rt-b")
    db_session.add(Prompt(org_id=org.id, name="dup", tags=[]))
    await db_session.flush()
    db_session.add(Prompt(org_id=org.id, name="dup", tags=[]))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_prompt_name_can_repeat_across_orgs(db_session: AsyncSession) -> None:
    _, org_a = await _seed_user_org(db_session, email="c@example.com", slug="rt-c1")
    org_b = Org(name="B", slug=f"rt-c2-{uuid4().hex[:6]}")
    db_session.add(org_b)
    await db_session.flush()

    db_session.add(Prompt(org_id=org_a.id, name="shared", tags=[]))
    db_session.add(Prompt(org_id=org_b.id, name="shared", tags=[]))
    await db_session.flush()  # no error


async def test_prompt_version_unique_per_prompt(db_session: AsyncSession) -> None:
    _, org = await _seed_user_org(db_session, email="d@example.com", slug="rt-d")
    prompt = Prompt(org_id=org.id, name="p", tags=[])
    db_session.add(prompt)
    await db_session.flush()
    db_session.add(PromptVersion(prompt_id=prompt.id, version=1, body="a"))
    await db_session.flush()
    db_session.add(PromptVersion(prompt_id=prompt.id, version=1, body="b"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_prompt_delete_cascades_to_versions(db_session: AsyncSession) -> None:
    _, org = await _seed_user_org(db_session, email="e@example.com", slug="rt-e")
    prompt = Prompt(org_id=org.id, name="p", tags=[])
    db_session.add(prompt)
    await db_session.flush()
    db_session.add(PromptVersion(prompt_id=prompt.id, version=1, body="a"))
    db_session.add(PromptVersion(prompt_id=prompt.id, version=2, body="b"))
    await db_session.flush()

    await db_session.delete(prompt)
    await db_session.flush()
    remaining = (
        await db_session.execute(select(PromptVersion).where(PromptVersion.prompt_id == prompt.id))
    ).first()
    assert remaining is None


async def test_creator_delete_sets_created_by_null(db_session: AsyncSession) -> None:
    from sqlalchemy import text

    user, org = await _seed_user_org(db_session, email="f@example.com", slug="rt-f")
    prompt = Prompt(org_id=org.id, name="p", tags=[], created_by=user.id)
    db_session.add(prompt)
    await db_session.flush()

    await db_session.delete(user)
    await db_session.flush()

    # Bypass the ORM identity map — the in-session Prompt instance still
    # remembers its old created_by even though the DB-level FK ondelete=SET NULL
    # has nulled it on disk.
    result = await db_session.execute(
        text("SELECT created_by FROM prompts WHERE id = :id"), {"id": prompt.id}
    )
    assert result.scalar_one() is None
