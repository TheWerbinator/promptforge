"""Minimal declarations of apps/api-owned tables that ragent's models reference.

ragent's models carry foreign keys to apps/api's `orgs` and `users`. SQLAlchemy
must resolve those FK targets within `Base.metadata` to flush an insert or sort
tables — without them, inserting a Corpus / Conversation / etc. raises
`NoReferencedTableError`. ragent doesn't own or migrate these tables (apps/api
does), so these are *partial* declarations: just enough for FK resolution (plus
the `slug`/`name` the demo-resolver tests build via `create_all`). They are never
`create_all`'d in production — apps/api's migrations create the real tables.

Imported for its side effect (registering the tables on `Base.metadata`).
"""

from sqlalchemy import Column, String, Table
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from promptforge_ragent.models.base import Base

orgs_table = Table(
    "orgs",
    Base.metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("slug", String),
    Column("name", String),
)

users_table = Table(
    "users",
    Base.metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
)
