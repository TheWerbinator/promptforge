"""Discover apps/api-owned demo entities from the shared database (read-only).

apps/api owns orgs, memberships, and prompts and seeds them with random ids, so
ragent can't hardcode those ids. Instead it discovers what it needs by natural
key — the demo org by slug, a user via that org's membership, the agent's system
prompt by name — using small read-only queries against the shared schema. ragent
doesn't model these api tables, so these are raw `text()` lookups; the discovered
ids then drive the service-JWT mint and the seed's corpus ownership.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DemoPrincipal:
    org_id: UUID
    user_id: UUID


async def resolve_demo_principal(session: AsyncSession, slug: str) -> DemoPrincipal | None:
    """Return the demo org + a member user id, or None if the org isn't seeded."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT o.id AS org_id, m.user_id AS user_id "
                    "FROM orgs o JOIN memberships m ON m.org_id = o.id "
                    "WHERE o.slug = :slug ORDER BY m.user_id LIMIT 1"
                ),
                {"slug": slug},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return DemoPrincipal(org_id=row["org_id"], user_id=row["user_id"])


async def resolve_prompt_version_id(session: AsyncSession, org_id: UUID, name: str) -> UUID | None:
    """Return the latest version id of the org's prompt named `name`, or None."""
    return (
        await session.execute(
            text(
                "SELECT pv.id FROM prompt_versions pv "
                "JOIN prompts p ON pv.prompt_id = p.id "
                "WHERE p.org_id = :org AND p.name = :name "
                "ORDER BY pv.version DESC LIMIT 1"
            ),
            {"org": org_id, "name": name},
        )
    ).scalar_one_or_none()
