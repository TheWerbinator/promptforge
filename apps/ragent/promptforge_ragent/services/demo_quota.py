"""Free-turn quota for the demo agent (per-IP + global daily caps).

Demo visitors get a few free hosted-key agent turns per day before they must
supply their own provider key. Two counters bound the hosted-key cost:

- **per-IP** (`HMAC(ip)`/day): stops a single casual visitor over-using, good UX.
- **global** (one sentinel row/day): caps *total* free turns across everyone —
  the real defense against IP/VPN rotation, which makes per-IP limits alone
  ineffective. Reliable VPN *detection* needs a paid reputation service and is an
  arms race; a global ceiling makes rotation pointless instead.

A turn is "free" only when a demo principal runs without BYOK. The IP is stored
as an HMAC (shared JWT secret) — no raw addresses at rest.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.models import GLOBAL_USAGE_KEY


def client_ip(request: Request) -> str:
    """Best-effort client IP, honoring Fly's + standard forwarding headers."""
    fly = request.headers.get("fly-client-ip")
    if fly:
        return fly.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"  # noqa: S104 — fallback, not a bind


def hmac_ip(ip: str) -> str:
    secret = get_settings().jwt_secret.get_secret_value().encode()
    return hmac.new(secret, ip.encode(), hashlib.sha256).hexdigest()


async def _turns(session: AsyncSession, key: str, day: object) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT turns FROM ragent_demo_usage WHERE ip_hmac = :key AND usage_day = :day"
                ),
                {"key": key, "day": day},
            )
        ).scalar_one_or_none()
        or 0
    )


async def free_turns_remaining(session: AsyncSession, ip_hmac: str) -> int:
    """Free turns left for this visitor today — the lesser of per-IP and global."""
    settings = get_settings()
    day = datetime.now(UTC).date()
    per_ip = max(0, settings.demo_free_turns_per_ip - await _turns(session, ip_hmac, day))
    glob = max(0, settings.demo_free_turns_global - await _turns(session, GLOBAL_USAGE_KEY, day))
    return min(per_ip, glob)


async def record_free_turn(session: AsyncSession, ip_hmac: str) -> None:
    """Atomically increment the per-IP and global counters for today."""
    day = datetime.now(UTC).date()
    for key in (ip_hmac, GLOBAL_USAGE_KEY):
        await session.execute(
            text(
                "INSERT INTO ragent_demo_usage (id, ip_hmac, usage_day, turns) "
                "VALUES (gen_random_uuid(), :key, :day, 1) "
                "ON CONFLICT (ip_hmac, usage_day) "
                "DO UPDATE SET turns = ragent_demo_usage.turns + 1, updated_at = now()"
            ),
            {"key": key, "day": day},
        )
