"""Structured logging (structlog) + a request-context ASGI middleware.

JSON logs in deployed environments, a human-readable console renderer when
PF_LOG_LEVEL=DEBUG. Every log line inside a request carries the request id via
structlog contextvars, and the same id goes back on the `X-Request-ID` response
header so a user can quote it in a bug report and we can grep for it.

The middleware is raw ASGI on purpose: Starlette's BaseHTTPMiddleware buffers the
response body, which would break the SSE eval stream. A send-wrapper touches only
the response-start headers, leaving the streaming body untouched.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from promptforge_api.core.config import Settings, get_settings

if TYPE_CHECKING:
    from structlog.types import Processor

log = structlog.get_logger("promptforge.request")


def configure_logging(settings: Settings | None = None) -> None:
    """Idempotent-ish: safe to call once at startup. Picks JSON vs console by level."""
    settings = settings or get_settings()
    level = logging.getLevelName(settings.log_level)  # str -> int

    # Library logs (uvicorn, sqlalchemy) flow through the stdlib root at the same
    # level; our own logs go through structlog's own pipeline below.
    logging.basicConfig(format="%(message)s", level=level)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Processor = (
        structlog.dev.ConsoleRenderer()
        if settings.log_level == "DEBUG"
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _header(scope_headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in scope_headers:
        if key == name:
            return value.decode("latin-1")
    return None


class RequestContextMiddleware:
    """Bind a request id to the log context, time the request, echo the id back."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _header(scope.get("headers", []), b"x-request-id") or uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            log.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                duration_ms=duration_ms,
            )
            structlog.contextvars.clear_contextvars()
