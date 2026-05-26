"""Org-scoped repository base class.

Every business resource that carries an `org_id` column is accessed through
`TenantRepository`. Filtering by the current principal's `org_id` is automatic
and unbypassable — there is no escape hatch for routes to query without the
org filter. This is the load-bearing invariant of the multi-tenant design.

Cross-org access returns `None` from `get()` (and 404 from `get_or_404`) rather
than raising 403 so we don't leak the existence of resources in other orgs.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.core.deps import Principal
from promptforge_api.models.base import Base

T = TypeVar("T", bound=Base)


class TenantRepository(Generic[T]):
    def __init__(self, model: type[T], session: AsyncSession, principal: Principal):
        if not hasattr(model, "org_id"):
            raise ValueError(
                f"{model.__name__} has no org_id column; "
                "TenantRepository is for org-scoped models only"
            )
        self.model = model
        self.session = session
        self.principal = principal
        self.org_id = principal.org_id

    async def get(self, id_: UUID) -> T | None:
        """Fetch by id; returns None if absent OR in another org."""
        row = await self.session.get(self.model, id_)
        if row is None or row.org_id != self.org_id:  # type: ignore[attr-defined]
            return None
        return row

    async def get_or_404(self, id_: UUID) -> T:
        row = await self.get(id_)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{self.model.__name__.lower()} not found",
            )
        return row

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        order_by: Any | None = None,
    ) -> list[T]:
        stmt = (
            select(self.model)
            .where(self.model.org_id == self.org_id)  # type: ignore[attr-defined]
            .offset(offset)
            .limit(limit)
        )
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def count(self) -> int:
        stmt = (
            select(func.count()).select_from(self.model).where(self.model.org_id == self.org_id)  # type: ignore[attr-defined]
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def add(self, **fields: Any) -> T:
        """Insert a new row scoped to the principal's org.

        If `org_id` is supplied it must match the principal's org — guards
        against accidental cross-org writes from buggy callers.
        """
        provided_org = fields.get("org_id")
        if provided_org is not None and provided_org != self.org_id:
            raise ValueError("cannot create entity for a different org")
        fields["org_id"] = self.org_id
        instance = self.model(**fields)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, id_: UUID) -> bool:
        row = await self.get(id_)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True
