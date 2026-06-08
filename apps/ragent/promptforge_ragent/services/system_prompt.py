"""Resolve + fetch the agent's system prompt (cached, with a fallback).

This is the platform-integration story: the agent's behavior is governed by a
prompt *managed in apps/api*. ragent discovers which prompt to use from the
shared DB by natural key (the demo org + the configured prompt name), then
fetches its body from apps/api over HTTP — authenticated by a short-lived JWT
minted with the shared HS256 secret for the demo principal, so apps/api validates
it like any token with no round-trip. Editing the prompt in PromptForge changes
the agent on the next cache miss.

If the prompt isn't seeded yet or the fetch fails, the agent falls back to a
built-in default so it always works. Resolved bodies (and the unconfigured
default) are cached for `system_prompt_cache_seconds`; a *failed* fetch is not
cached, so the agent recovers on the next request once apps/api is back.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.services.platform import (
    DemoPrincipal,
    resolve_demo_principal,
    resolve_prompt_version_id,
)

log = structlog.get_logger("promptforge.ragent.system_prompt")

_JWT_ALG = "HS256"
_SERVICE_TOKEN_TTL = timedelta(minutes=5)
_FETCH_TIMEOUT_S = 5.0

DEFAULT_SYSTEM_PROMPT = (
    "You are PromptForge's documentation assistant. Answer the user's question "
    "using only the knowledge base, which you access through the provided tools. "
    "Search before you answer, fetch a full passage when a snippet is truncated, "
    "and call cite_sources with the chunk_ids you relied on before giving your "
    "final answer. If the answer isn't in the corpus, say so plainly rather than "
    "guessing."
)

# (monotonic_timestamp, prompt) — module-level TTL cache.
_cache: tuple[float, str] | None = None


def _service_token(principal: DemoPrincipal) -> str:
    """Mint a short-lived access JWT for the demo principal (shared HS256 secret)."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(principal.user_id),
        "org": str(principal.org_id),
        "role": "member",
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + _SERVICE_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, get_settings().jwt_secret.get_secret_value(), algorithm=_JWT_ALG)


async def _fetch_version_body(base_url: str, version_id: str, token: str) -> str:
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S) as client:
        resp = await client.get(
            f"{base_url.rstrip('/')}/api/v1/versions/{version_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        body = resp.json().get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("version response missing a usable body")
    return body


async def get_system_prompt(session: AsyncSession) -> str:
    """Return the agent system prompt — resolved from apps/api, cached, or default."""
    global _cache
    settings = get_settings()
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < settings.system_prompt_cache_seconds:
        return _cache[1]

    principal = await resolve_demo_principal(session, settings.demo_org_slug)
    version_id = (
        await resolve_prompt_version_id(session, principal.org_id, settings.system_prompt_name)
        if principal is not None
        else None
    )
    if principal is None or version_id is None:
        # Not seeded yet — cache the default (it won't change until it's seeded).
        _cache = (now, DEFAULT_SYSTEM_PROMPT)
        return DEFAULT_SYSTEM_PROMPT

    try:
        body = await _fetch_version_body(
            settings.api_base_url, str(version_id), _service_token(principal)
        )
    except Exception as exc:  # network, 4xx/5xx, malformed — fall back, don't cache
        log.warning("system_prompt_fetch_failed", error=str(exc))
        return DEFAULT_SYSTEM_PROMPT

    _cache = (now, body)
    return body


def _reset_cache() -> None:
    """Test hook: drop the cached prompt."""
    global _cache
    _cache = None
