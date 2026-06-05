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
    from sqlalchemy import Column, Table
    from sqlalchemy.dialects.postgresql import UUID as PgUUID

    from promptforge_ragent.models import Base

    for parent in ("orgs", "users"):
        if parent not in Base.metadata.tables:
            Table(parent, Base.metadata, Column("id", PgUUID(as_uuid=True), primary_key=True))

    engine = create_async_engine(pg_url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
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

    await engine.dispose()
