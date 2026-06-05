"""Alembic environment using asyncpg (no separate sync driver dependency)."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from promptforge_api.core.config import get_settings
from promptforge_api.models import Base

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _async_db_url() -> str:
    """Return a SQLAlchemy DSN normalized to use the asyncpg driver.

    Provider DSNs (Neon, Fly Postgres) use bare `postgresql://` which SQLAlchemy
    routes to psycopg2 by default — that's the sync driver we don't ship.
    Settings.async_database_url() rewrites the scheme + sslmode→ssl param.
    """
    return get_settings().async_database_url()


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Keep autogenerate from touching tables apps/api doesn't own.

    apps/ragent's tables (corpora, documents, chunks, conversations, messages)
    live in the same shared database but are not in apps/api's metadata. Without
    this filter, `alembic revision --autogenerate` would diff the live DB against
    api's metadata, not see those tables there, and emit DROP TABLE for them.
    Ignoring any table not in our own metadata makes api a safe co-migrator of
    the shared DB. (Affects autogenerate only; applying migrations is unaffected.)
    """
    if type_ == "table" and name not in target_metadata.tables:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_async_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _async_db_url()

    connectable = async_engine_from_config(section, prefix="sqlalchemy.")

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
