"""Integration tests for the base models against real Postgres."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.models import Membership, Org, OrgRole, User

pytestmark = pytest.mark.integration


async def test_create_user_and_round_trip(db_session: AsyncSession) -> None:
    user = User(email="jane@example.com", password_hash="x" * 64, display_name="Jane")
    db_session.add(user)
    await db_session.flush()

    fetched = (
        await db_session.execute(select(User).where(User.email == "jane@example.com"))
    ).scalar_one()

    assert fetched.id == user.id
    assert fetched.is_active is True
    assert fetched.created_at is not None


async def test_user_email_unique(db_session: AsyncSession) -> None:
    db_session.add(User(email="dup@example.com", password_hash="a" * 64))
    await db_session.flush()

    db_session.add(User(email="dup@example.com", password_hash="b" * 64))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_create_org_and_membership(db_session: AsyncSession) -> None:
    user = User(email="owner@example.com", password_hash="x" * 64)
    org = Org(name="Acme", slug="acme")
    db_session.add_all([user, org])
    await db_session.flush()

    membership = Membership(user_id=user.id, org_id=org.id, role=OrgRole.OWNER)
    db_session.add(membership)
    await db_session.flush()

    fetched = (
        await db_session.execute(
            select(Membership).where(Membership.user_id == user.id, Membership.org_id == org.id)
        )
    ).scalar_one()

    assert fetched.role is OrgRole.OWNER


async def test_membership_unique_per_user_org(db_session: AsyncSession) -> None:
    user = User(email="dup-member@example.com", password_hash="x" * 64)
    org = Org(name="Acme 2", slug="acme2")
    db_session.add_all([user, org])
    await db_session.flush()

    db_session.add(Membership(user_id=user.id, org_id=org.id, role=OrgRole.OWNER))
    await db_session.flush()

    db_session.add(Membership(user_id=user.id, org_id=org.id, role=OrgRole.MEMBER))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_org_slug_unique(db_session: AsyncSession) -> None:
    db_session.add(Org(name="Acme A", slug="dup-slug"))
    await db_session.flush()

    db_session.add(Org(name="Acme B", slug="dup-slug"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_cascade_delete_user_removes_memberships(db_session: AsyncSession) -> None:
    user = User(email="cascade@example.com", password_hash="x" * 64)
    org = Org(name="Cascade Org", slug="cascade")
    db_session.add_all([user, org])
    await db_session.flush()

    db_session.add(Membership(user_id=user.id, org_id=org.id, role=OrgRole.MEMBER))
    await db_session.flush()

    await db_session.delete(user)
    await db_session.flush()

    remaining = (
        (await db_session.execute(select(Membership).where(Membership.user_id == user.id)))
        .scalars()
        .all()
    )
    assert remaining == []
