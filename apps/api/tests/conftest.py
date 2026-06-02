"""Shared pytest fixtures.

`isolate_env` runs autouse so tests never see ambient env vars that could leak from
the developer's shell. Tests opt in to specific env via the `base_env` fixture or by
setting vars via `monkeypatch`.

Integration tests use `pg_container` (session-scoped testcontainers Postgres) and
`db_session` (per-test transactional rollback). E2E and tenancy tests use
`api_client` (real ASGI app + truncate-between-tests Postgres).
"""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from promptforge_api.core.db import dispose_engine, get_session

if TYPE_CHECKING:
    from testcontainers.postgres import PostgresContainer

API_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = API_ROOT / "alembic.ini"
ALEMBIC_DIR = API_ROOT / "alembic"


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "PF_DATABASE_URL",
        "PF_JWT_SECRET",
        "PF_LOG_LEVEL",
        "PF_CORS_ORIGINS",
        "PF_OPENAI_API_KEY",
        "PF_ANTHROPIC_API_KEY",
        "PF_DEMO_EMAIL",
        "PF_DEMO_RATE_LIMIT",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimum env required for `Settings()` to load."""
    monkeypatch.setenv(
        "PF_DATABASE_URL",
        "postgresql+asyncpg://test:test@localhost:5432/test",
    )
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)


# ----- Integration fixtures (testcontainers Postgres) ---------------------------------


@pytest.fixture(scope="session")
def pg_container() -> Iterator["PostgresContainer"]:
    """Session-scoped Postgres container. Skipped if Docker is unavailable."""
    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def pg_url(pg_container: "PostgresContainer") -> str:
    return pg_container.get_connection_url()


@pytest.fixture(scope="session")
def _migrated_engine(pg_url: str) -> None:
    """Run Alembic migrations once per session against the container."""
    from alembic.config import Config

    from alembic import command

    os.environ["PF_DATABASE_URL"] = pg_url
    os.environ.setdefault("PF_JWT_SECRET", "a" * 48)

    from promptforge_api.core.config import get_settings

    get_settings.cache_clear()

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def db_session(pg_url: str, _migrated_engine: None) -> AsyncIterator[AsyncSession]:
    """Per-test session with rollback isolation. Each test sees a clean DB state."""
    engine = create_async_engine(pg_url, future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with engine.connect() as connection:
        trans = await connection.begin()
        session = session_factory(bind=connection)

        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()

    await engine.dispose()


# ----- E2E / tenancy: full ASGI app + truncate-per-test --------------------------------


@pytest_asyncio.fixture
async def api_client(
    pg_url: str,
    _migrated_engine: None,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("PF_DATABASE_URL", pg_url)
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    monkeypatch.setenv("PF_COOKIE_SECURE", "false")

    from promptforge_api.core.config import get_settings

    get_settings.cache_clear()

    # Per-test engine. We bind it to the app via dependency_overrides rather than
    # mutating the module-global engine — that global was the source of flaky
    # cross-test failures when one test's dispose raced another's pool.
    test_engine = create_async_engine(pg_url, future=True)
    truncate_sql = (
        "TRUNCATE share_tokens, eval_results, eval_batches, eval_cases, eval_suites, "
        "runs, jobs, prompt_versions, prompts, refresh_tokens, "
        "api_keys, demo_usage, memberships, orgs, users RESTART IDENTITY CASCADE"
    )
    async with test_engine.begin() as conn:
        await conn.execute(text(truncate_sql))

    # Reset the slowapi limiter's in-memory counters so per-test rate-limit state
    # doesn't bleed across tests (the demo-login limit is keyed on a constant
    # TestClient IP, so without this every test shares one bucket).
    from promptforge_api.core.ratelimit import limiter

    limiter.reset()

    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    from promptforge_api.main import create_app

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    # Dispose BOTH the per-test engine and the global engine that some routes
    # (Queue.enqueue, _drain_queue in tests) use directly via get_session_factory().
    # Leaving the global engine alive across tests leaks asyncpg connections
    # bound to closed event loops — manifests as "Event loop is closed" during
    # later pool teardown.
    await dispose_engine()
    await test_engine.dispose()
