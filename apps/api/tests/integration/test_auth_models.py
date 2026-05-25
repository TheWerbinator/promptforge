"""Integration tests for ApiKey + RefreshToken models against real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.models import ApiKey, Org, OrgRole, RefreshToken, User

pytestmark = pytest.mark.integration


async def _make_user_and_org(
    session: AsyncSession, *, email: str = "user@example.com", slug: str = "acme"
) -> tuple[User, Org]:
    user = User(email=email, password_hash="x" * 64)
    org = Org(name="Acme", slug=slug)
    session.add_all([user, org])
    await session.flush()
    return user, org


async def test_api_key_insert_and_lookup_by_prefix(db_session: AsyncSession) -> None:
    user, org = await _make_user_and_org(db_session, email="a@example.com", slug="a")
    db_session.add(
        ApiKey(
            org_id=org.id,
            user_id=user.id,
            name="ci",
            key_hash="hash",
            prefix="abcd1234",
        )
    )
    await db_session.flush()

    row = (await db_session.execute(select(ApiKey).where(ApiKey.prefix == "abcd1234"))).scalar_one()
    assert row.name == "ci"
    assert row.revoked_at is None


async def test_api_key_cascade_on_user_delete(db_session: AsyncSession) -> None:
    user, org = await _make_user_and_org(db_session, email="b@example.com", slug="b")
    db_session.add(
        ApiKey(
            org_id=org.id,
            user_id=user.id,
            name="ci",
            key_hash="h",
            prefix="ppppffff",
        )
    )
    await db_session.flush()

    await db_session.delete(user)
    await db_session.flush()
    assert (
        await db_session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    ).first() is None


async def test_refresh_token_unique_hmac(db_session: AsyncSession) -> None:
    user, org = await _make_user_and_org(db_session, email="c@example.com", slug="c")
    now = datetime.now(UTC)
    db_session.add(
        RefreshToken(
            user_id=user.id,
            org_id=org.id,
            chain_id=uuid4(),
            token_hmac="duphmac",
            expires_at=now + timedelta(days=30),
        )
    )
    await db_session.flush()
    db_session.add(
        RefreshToken(
            user_id=user.id,
            org_id=org.id,
            chain_id=uuid4(),
            token_hmac="duphmac",
            expires_at=now + timedelta(days=30),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_refresh_token_parent_chain_links(db_session: AsyncSession) -> None:
    user, org = await _make_user_and_org(db_session, email="d@example.com", slug="d")
    now = datetime.now(UTC)
    chain_id = uuid4()
    parent = RefreshToken(
        user_id=user.id,
        org_id=org.id,
        chain_id=chain_id,
        token_hmac="parent",
        expires_at=now + timedelta(days=30),
    )
    db_session.add(parent)
    await db_session.flush()
    child = RefreshToken(
        user_id=user.id,
        org_id=org.id,
        chain_id=chain_id,
        token_hmac="child",
        parent_id=parent.id,
        expires_at=now + timedelta(days=30),
    )
    db_session.add(child)
    await db_session.flush()

    rows = (
        (await db_session.execute(select(RefreshToken).where(RefreshToken.chain_id == chain_id)))
        .scalars()
        .all()
    )
    assert {r.token_hmac for r in rows} == {"parent", "child"}


async def test_refresh_token_membership_assumes_org_role_demo(
    db_session: AsyncSession,
) -> None:
    """Smoke test that OrgRole.DEMO is persistable for refresh-token rows."""
    user, org = await _make_user_and_org(db_session, email="e@example.com", slug="e")
    # this isn't on the refresh model but exercises the enum end-to-end
    from promptforge_api.models import Membership

    db_session.add(Membership(user_id=user.id, org_id=org.id, role=OrgRole.DEMO))
    await db_session.flush()

    membership = (
        await db_session.execute(select(Membership).where(Membership.user_id == user.id))
    ).scalar_one()
    assert membership.role is OrgRole.DEMO
