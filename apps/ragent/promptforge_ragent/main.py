"""FastAPI application entrypoint for the ragent service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from promptforge_ragent import __version__
from promptforge_ragent.api.v1 import api_router
from promptforge_ragent.core.config import get_settings
from promptforge_ragent.core.logging import RequestContextMiddleware, configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="PromptForge ragent",
        version=__version__,
        lifespan=lifespan,
    )

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
