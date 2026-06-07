"""documents.raw_content: store source bytes for async (worker-driven) ingest

ragent's ingest worker is detached from whatever produced a document (an upload
handler, the seed), so it can't be handed the bytes in-process — it reads them
back from the row. `raw_content` holds the original file bytes; the worker parses
→ chunks → embeds from it, and it's retained so a re-ingest (re-chunk with new
params) needs no re-upload. At demo scale (5 MB/file cap) bytea in Postgres is
fine; object storage (S3/R2) is the documented scale path. Owned here because
apps/api is the single migrator of the shared DB; the column is mapped by
ragent's Document model.

Revision ID: 20260605_0010
Revises: 20260605_0009
Create Date: 2026-06-05
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260605_0010"
down_revision: str | None = "20260605_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("raw_content", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "raw_content")
