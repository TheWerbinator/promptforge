"""add demo_usage table

Revision ID: 20260601_0007
Revises: 20260601_0006
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260601_0007"
down_revision: str | None = "20260601_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.PrimaryKeyConstraint("id", name="pk_demo_usage"),
        sa.UniqueConstraint("ip_hash", "day", name="uq_demo_usage_ip_hash_day"),
    )
    op.create_index("ix_demo_usage_ip_hash", "demo_usage", ["ip_hash"])


def downgrade() -> None:
    op.drop_index("ix_demo_usage_ip_hash", table_name="demo_usage")
    op.drop_table("demo_usage")
