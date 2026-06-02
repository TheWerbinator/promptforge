"""slowapi rate limiter, shared across the app.

A single module-global `Limiter` so route decorators (`@limiter.limit(...)`) and
the app wiring in main.py reference the same instance. Storage defaults to
in-process memory — fine for a single api machine on Fly; if we scaled the api
horizontally we'd point slowapi at Redis so the counters are shared.

`client_ip` is also the limiter's key function. slowapi ships `get_ipaddr`, but
it keys off `request.client.host` (or a mis-cased `X_FORWARDED_FOR`), which is
the Fly proxy's address — every visitor would share one bucket. We trust the
forwarded headers Fly actually sets instead.
"""

from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request


def client_ip(request: Request) -> str:
    """Best-effort real client IP, accounting for the Fly proxy in front of us."""
    fly = request.headers.get("fly-client-ip")
    if fly:
        return fly
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First hop is the original client; the rest are proxies.
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


limiter = Limiter(key_func=client_ip)
