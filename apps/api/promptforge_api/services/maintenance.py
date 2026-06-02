"""Periodic maintenance tasks. Run from the worker process.

Currently just the refresh-token reaper. Kept as plain functions (no scheduling
here) so they're unit-testable; the worker owns the interval loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete

from promptforge_api.models import RefreshToken

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def reap_expired_refresh_tokens(session: AsyncSession, *, retention_days: int) -> int:
    """Hard-delete refresh tokens whose expires_at is older than the retention
    window. Revoked/replaced tokens still occupy rows until they age out this way;
    keeping them until expiry preserves the chain-revocation audit trail, after
    which they're just dead weight. Returns the number of rows deleted."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(delete(RefreshToken).where(RefreshToken.expires_at < cutoff))
    # rowcount lives on CursorResult; AsyncSession.execute is typed as Result.
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
