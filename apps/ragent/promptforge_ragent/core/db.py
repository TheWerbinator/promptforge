"""Async SQLAlchemy engine + session management.

Mirrors apps/api's db module: a lazily-built async engine (so importing this
doesn't require PF_DATABASE_URL — matters for test collection) and a
`get_session` FastAPI dependency that yields a transactional session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from promptforge_ragent.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.async_database_url(),
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        future=True,
    )


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = _build_engine()
        _session_factory = async_sessionmaker(
            bind=_engine,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a session, commit on success, rollback on error."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the cached engine. Used by tests and graceful shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
