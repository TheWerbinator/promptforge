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
from promptforge_api.core.ratelimit import limiter


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # TODO(phase-16): wire structlog here (json formatter in prod, dev-friendly
    # console formatter when PF_LOG_LEVEL=DEBUG) and init OpenTelemetry tracing
    # against the Fly OTel exporter.
    get_settings()
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

    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
