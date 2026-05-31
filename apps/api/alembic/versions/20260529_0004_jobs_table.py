"""add jobs table for Postgres-backed queue

Revision ID: 20260529_0004
Revises: 20260525_0003
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260529_0004"
down_revision: str | None = "20260525_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    # Partial index — only queued rows participate. Keeps the claim query cheap
    # as done/failed rows accumulate (until the phase-13 reaper hard-deletes them).
    op.create_index(
        "ix_jobs_pull",
        "jobs",
        ["kind", "run_after"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index("ix_jobs_batch", "jobs", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_batch", table_name="jobs")
    op.drop_index("ix_jobs_pull", table_name="jobs")
    op.drop_table("jobs")
