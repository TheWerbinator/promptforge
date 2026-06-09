"""Shared pytest fixtures.

`isolate_env` (autouse) keeps ambient `PF_*` vars out of tests; `base_env` sets
the minimum env for `Settings()` to load.

Integration fixtures use a **pgvector** Postgres container. ragent doesn't own
the migration history (apps/api does), so the test schema is built from ragent's
own metadata via `create_all`, after stubbing the api-owned parent tables
(`orgs`, `users`) that ragent's foreign keys point at. This keeps ragent's tests
self-contained without importing the api package.
"""

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from promptforge_ragent.core.config import get_settings

if TYPE_CHECKING:
    from httpx import AsyncClient
    from testcontainers.postgres import PostgresContainer

# pgvector preinstalled; CREATE EXTENSION still required per-database.
PG_IMAGE = "pgvector/pgvector:pg17"


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for var in (
        "PF_DATABASE_URL",
        "PF_JWT_SECRET",
        "PF_API_BASE_URL",
        "PF_LOG_LEVEL",
        "PF_CORS_ORIGINS",
        "PF_OPENAI_API_KEY",
        "PF_ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimum env required for `Settings()` to load."""
    monkeypatch.setenv(
        "PF_DATABASE_URL",
        "postgresql+asyncpg://test:test@localhost:5432/test",
    )
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()


# ----- Integration fixtures (pgvector testcontainers Postgres) -------------------------


@pytest.fixture(scope="session")
def pg_container() -> Iterator["PostgresContainer"]:
    """Session-scoped pgvector Postgres container. Skipped if Docker is unavailable."""
    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(PG_IMAGE, driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def pg_url(pg_container: "PostgresContainer") -> str:
    return pg_container.get_connection_url()


@pytest_asyncio.fixture(scope="session")
async def _schema(pg_url: str) -> None:
    """Build the ragent schema once per session.

    Enables pgvector, then creates ragent's tables (+ ivfflat indexes) from its
    own metadata. ragent's FKs point at apps/api's `orgs`/`users`; those tables
    aren't in ragent's metadata, so we register minimal stand-ins (just the PK
    column the FKs resolve against) in the same metadata — otherwise create_all
    can't resolve the FK targets. The real tables come from api's migrations in
    every non-test environment.
    """
    # `orgs`/`users` are declared on Base.metadata by promptforge_ragent.models
    # (models/_external.py) — importing Base registers them — so create_all builds
    # them and ragent's FK targets resolve, the same as in production.
    from promptforge_ragent.models import Base

    engine = create_async_engine(pg_url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Stubs of api-owned tables the resolver/seed read by raw SQL (subset of
        # columns). Not in ragent's metadata (no ragent FK points at them); the
        # real tables come from api's migrations everywhere else.
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS memberships ("
                "  user_id UUID NOT NULL, org_id UUID NOT NULL)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS prompts ("
                "  id UUID PRIMARY KEY, org_id UUID NOT NULL, name TEXT NOT NULL)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS prompt_versions ("
                "  id UUID PRIMARY KEY, prompt_id UUID NOT NULL, version INTEGER NOT NULL, "
                "  body TEXT NOT NULL)"
            )
        )
        # Stub of apps/api's `jobs` table (migration 0004) — just the columns
        # ragent's queue client touches. The real table is api-owned; ragent
        # shares it in every non-test environment.
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "  id BIGSERIAL PRIMARY KEY,"
                "  kind TEXT NOT NULL,"
                "  payload JSONB NOT NULL DEFAULT '{}'::jsonb,"
                "  batch_id UUID,"
                "  status TEXT NOT NULL DEFAULT 'queued',"
                "  attempts INTEGER NOT NULL DEFAULT 0,"
                "  max_attempts INTEGER NOT NULL DEFAULT 3,"
                "  run_after TIMESTAMPTZ NOT NULL DEFAULT now(),"
                "  claimed_at TIMESTAMPTZ,"
                "  finished_at TIMESTAMPTZ,"
                "  error TEXT,"
                "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                ")"
            )
        )
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(pg_url: str, _schema: None) -> AsyncIterator[AsyncSession]:
    """Per-test session with rollback isolation. Each test sees a clean DB."""
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


@pytest_asyncio.fixture
async def committed_db(
    pg_url: str, _schema: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Real (committing) session factory for queue/worker tests.

    The queue and worker open their own sessions and COMMIT (a worker must see
    what an enqueuer wrote), so rollback isolation won't do. This points ragent's
    module-global engine at the container and truncates the touched tables after
    each test. Yields the global session factory the queue/worker also use.
    """
    from promptforge_ragent.core.db import dispose_engine, get_session_factory

    monkeypatch.setenv("PF_DATABASE_URL", pg_url)
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()
    await dispose_engine()  # rebuild the global engine against the container

    factory = get_session_factory()
    try:
        yield factory
    finally:
        async with factory() as session:
            await session.execute(
                text(
                    "TRUNCATE jobs, chunks, documents, corpora, orgs, users, "
                    "memberships, prompts, prompt_versions, ragent_demo_usage "
                    "RESTART IDENTITY CASCADE"
                )
            )
            await session.commit()
        await dispose_engine()


@pytest_asyncio.fixture
async def app_client(
    committed_db: async_sessionmaker[AsyncSession],
) -> AsyncIterator["AsyncClient"]:
    """httpx client bound to the real ASGI app, sharing committed_db's env + engine.

    The chat SSE generator opens its own session via the global factory (which
    committed_db points at the container), so e2e tests hit the app and assert on
    persisted rows via the same factory. The SSE response is finite, so
    ASGITransport buffering it is fine.
    """
    from httpx import ASGITransport, AsyncClient

    from promptforge_ragent.main import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
