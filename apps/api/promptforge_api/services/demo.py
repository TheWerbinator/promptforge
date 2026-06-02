"""Demo free-run quota: per-IP, per-day counting of hosted-key runs.

Visitors get a handful of real runs on our hosted provider key before they have
to bring their own. The counter is keyed on a hash of the client IP (not the demo
session) so a visitor can't reset their quota just by logging in again, and so a
single visitor can't drain the budget for everyone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, text

from promptforge_api.core.security import hmac_token
from promptforge_api.models import DemoUsage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def ip_hash(client_ip: str) -> str:
    """HMAC the IP so we never store the raw address. Reuses the JWT secret."""
    return hmac_token(client_ip)


async def free_runs_remaining(session: AsyncSession, hashed_ip: str, *, limit: int) -> int:
    """How many free hosted-key runs this IP has left today."""
    today = datetime.now(UTC).date()
    used = (
        await session.execute(
            select(DemoUsage.run_count).where(
                DemoUsage.ip_hash == hashed_ip, DemoUsage.day == today
            )
        )
    ).scalar_one_or_none()
    return max(0, limit - (used or 0))


async def record_free_run(session: AsyncSession, hashed_ip: str) -> int:
    """Atomically increment today's counter for this IP; return the new count."""
    today = datetime.now(UTC).date()
    result = await session.execute(
        text(
            "INSERT INTO demo_usage (id, ip_hash, day, run_count, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :ip, :day, 1, now(), now()) "
            "ON CONFLICT (ip_hash, day) DO UPDATE SET "
            "  run_count = demo_usage.run_count + 1, updated_at = now() "
            "RETURNING run_count"
        ),
        {"ip": hashed_ip, "day": today},
    )
    return int(result.scalar_one())
