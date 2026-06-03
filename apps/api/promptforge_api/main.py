"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from promptforge_api import __version__
from promptforge_api.api.v1 import api_router
from promptforge_api.core.config import get_settings
from promptforge_api.core.logging import RequestContextMiddleware, configure_logging
from promptforge_api.core.ratelimit import limiter


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    # OTel seam: tracing is intentionally NOT wired. The single place to enable
    # it is here — initialize an OTLP exporter + FastAPI/asyncpg instrumentation
    # gated on OTEL_EXPORTER_OTLP_ENDPOINT. Deferred deliberately: a zero-traffic
    # demo shouldn't carry a ~5-package instrumentation stack it never exercises.
    # See docs/INTERVIEW-NOTES.md "Why structlog now but OTel deferred".
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="PromptForge API",
        version=__version__,
        lifespan=lifespan,
    )

    # Rate limiting (slowapi). The limiter is a module-global so route decorators
    # share it; the app just needs the instance on state + the 429 handler.
    app.state.limiter = limiter
    # slowapi's handler is typed for RateLimitExceeded specifically; Starlette's
    # add_exception_handler wants a handler over the base Exception (contravariant
    # param), so the precise type doesn't line up. Safe — the handler only ever
    # receives RateLimitExceeded.
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Added last → outermost: binds the request id before anything else runs and
    # guarantees X-Request-ID is set even on error responses.
    app.add_middleware(RequestContextMiddleware)

    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
