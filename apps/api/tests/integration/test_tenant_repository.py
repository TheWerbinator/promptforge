"""Integration tests for the TenantRepository base class.

Driven directly against real Postgres via the `db_session` fixture so we test
the actual filter SQL, not a mocked session.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.core.deps import Principal
from promptforge_api.models import ApiKey, Org, OrgRole, User
from promptforge_api.repositories import TenantRepository

pytestmark = pytest.mark.integration


def _principal(user_id: UUID, org_id: UUID, role: OrgRole = OrgRole.MEMBER) -> Principal:
    return Principal(user_id=user_id, org_id=org_id, role=role, auth="jwt")


async def _seed_two_orgs(db_session: AsyncSession) -> tuple[User, Org, Org]:
    user = User(email=f"u{uuid4().hex[:8]}@example.com", password_hash="x" * 64)
    org_a = Org(name="A", slug=f"a-{uuid4().hex[:8]}")
    org_b = Org(name="B", slug=f"b-{uuid4().hex[:8]}")
    db_session.add_all([user, org_a, org_b])
    await db_session.flush()
    return user, org_a, org_b


async def test_repository_rejects_models_without_org_id(db_session: AsyncSession) -> None:
    principal = _principal(uuid4(), uuid4())
    with pytest.raises(ValueError, match="org_id"):
        TenantRepository(User, db_session, principal)


async def test_get_returns_row_in_same_org(db_session: AsyncSession) -> None:
    user, org_a, _ = await _seed_two_orgs(db_session)
    repo = TenantRepository(ApiKey, db_session, _principal(user.id, org_a.id))
    row = await repo.add(user_id=user.id, name="k", key_hash="h", prefix="p" * 8)

    fetched = await repo.get(row.id)
    assert fetched is not None
    assert fetched.id == row.id


async def test_get_returns_none_for_other_org(db_session: AsyncSession) -> None:
    user, org_a, org_b = await _seed_two_orgs(db_session)
    repo_a = TenantRepository(ApiKey, db_session, _principal(user.id, org_a.id))
    row = await repo_a.add(user_id=user.id, name="k", key_hash="h", prefix="p" * 8)

    repo_b = TenantRepository(ApiKey, db_session, _principal(user.id, org_b.id))
    assert await repo_b.get(row.id) is None


async def test_list_excludes_other_orgs(db_session: AsyncSession) -> None:
    user, org_a, org_b = await _seed_two_orgs(db_session)
    repo_a = TenantRepository(ApiKey, db_session, _principal(user.id, org_a.id))
    repo_b = TenantRepository(ApiKey, db_session, _principal(user.id, org_b.id))

    await repo_a.add(user_id=user.id, name="ka", key_hash="h", prefix="a" * 8)
    await repo_b.add(user_id=user.id, name="kb", key_hash="h", prefix="b" * 8)

    a_rows = await repo_a.list()
    b_rows = await repo_b.list()
    assert {r.name for r in a_rows} == {"ka"}
    assert {r.name for r in b_rows} == {"kb"}


async def test_count_is_scoped(db_session: AsyncSession) -> None:
    user, org_a, org_b = await _seed_two_orgs(db_session)
    repo_a = TenantRepository(ApiKey, db_session, _principal(user.id, org_a.id))
    repo_b = TenantRepository(ApiKey, db_session, _principal(user.id, org_b.id))

    for i in range(3):
        await repo_a.add(user_id=user.id, name=f"a{i}", key_hash="h", prefix=f"a{i:07d}")
    await repo_b.add(user_id=user.id, name="b", key_hash="h", prefix="b" * 8)

    assert await repo_a.count() == 3
    assert await repo_b.count() == 1


async def test_add_rejects_cross_org_org_id(db_session: AsyncSession) -> None:
    user, org_a, org_b = await _seed_two_orgs(db_session)
    repo_a = TenantRepository(ApiKey, db_session, _principal(user.id, org_a.id))

    with pytest.raises(ValueError, match="different org"):
        await repo_a.add(
            user_id=user.id,
            org_id=org_b.id,
            name="k",
            key_hash="h",
            prefix="x" * 8,
        )


async def test_delete_other_org_returns_false(db_session: AsyncSession) -> None:
    user, org_a, org_b = await _seed_two_orgs(db_session)
    repo_a = TenantRepository(ApiKey, db_session, _principal(user.id, org_a.id))
    row = await repo_a.add(user_id=user.id, name="k", key_hash="h", prefix="d" * 8)

    repo_b = TenantRepository(ApiKey, db_session, _principal(user.id, org_b.id))
    assert await repo_b.delete(row.id) is False

    # Original repo still sees the row.
    assert await repo_a.get(row.id) is not None


async def test_get_or_404_raises_for_other_org(db_session: AsyncSession) -> None:
    from fastapi import HTTPException

    user, org_a, org_b = await _seed_two_orgs(db_session)
    repo_a = TenantRepository(ApiKey, db_session, _principal(user.id, org_a.id))
    row = await repo_a.add(user_id=user.id, name="k", key_hash="h", prefix="g" * 8)

    repo_b = TenantRepository(ApiKey, db_session, _principal(user.id, org_b.id))
    with pytest.raises(HTTPException) as exc_info:
        await repo_b.get_or_404(row.id)
    assert exc_info.value.status_code == 404
