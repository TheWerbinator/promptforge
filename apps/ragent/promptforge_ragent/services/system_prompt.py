"""Fetch the agent's system prompt live from apps/api (cached, with a fallback).

This is the platform-integration story: the agent's behavior is governed by a
prompt *managed in PromptForge*, so editing it in the UI changes the agent on the
next cache miss — not a redeploy. ragent authenticates the fetch by minting a
short-lived JWT with the shared HS256 secret for a configured service principal
(no round-trip to apps/api to validate — same-secret, same-control).

If the prompt isn't configured yet (the seed wires `system_prompt_version_id` +
the service principal) or the fetch fails, the agent falls back to a sane
built-in prompt so it always works. Successful fetches and the unconfigured
default are cached for `system_prompt_cache_seconds`; a *failed* fetch is not
cached, so the agent recovers on the next request once apps/api is back.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from jose import jwt

from promptforge_ragent.core.config import Settings, get_settings

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


def _service_token(settings: Settings) -> str | None:
    """Mint a short-lived access JWT for the service principal, or None if unset."""
    if not (settings.service_org_id and settings.service_user_id):
        return None
    now = datetime.now(UTC)
    payload = {
        "sub": settings.service_user_id,
        "org": settings.service_org_id,
        "role": "member",
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + _SERVICE_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=_JWT_ALG)


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


async def get_system_prompt() -> str:
    """Return the agent system prompt — fetched from apps/api, cached, or default."""
    global _cache
    settings = get_settings()
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < settings.system_prompt_cache_seconds:
        return _cache[1]

    version_id = settings.system_prompt_version_id
    token = _service_token(settings)
    if version_id and token:
        try:
            body = await _fetch_version_body(settings.api_base_url, version_id, token)
        except Exception as exc:  # network, 4xx/5xx, malformed — fall back, don't cache
            log.warning("system_prompt_fetch_failed", error=str(exc))
            return DEFAULT_SYSTEM_PROMPT
        _cache = (now, body)
        return body

    # Not configured yet: cache the default (it won't change until configured).
    _cache = (now, DEFAULT_SYSTEM_PROMPT)
    return DEFAULT_SYSTEM_PROMPT


def _reset_cache() -> None:
    """Test hook: drop the cached prompt."""
    global _cache
    _cache = None
