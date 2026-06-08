"""ragent_demo_usage: per-day free-turn counter for the demo agent

ragent's domain (demo cost control for the chat agent), but apps/api owns the
single migration history for the shared DB, so the DDL lives here. Hand-authored
like the other ragent tables; mapped by ragent's DemoUsage model. Outside
tenancy (per-IP, not per-org).

Revision ID: 20260608_0011
Revises: 20260605_0010
Create Date: 2026-06-08
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260608_0011"
down_revision: str | None = "20260605_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ragent_demo_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ip_hmac", sa.String(length=128), nullable=False),
        sa.Column("usage_day", sa.Date(), nullable=False),
        sa.Column("turns", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_ragent_demo_usage"),
        sa.UniqueConstraint("ip_hmac", "usage_day", name="uq_ragent_demo_usage_ip_day"),
    )
    op.create_index(op.f("ix_ragent_demo_usage_ip_hmac"), "ragent_demo_usage", ["ip_hmac"])


def downgrade() -> None:
    op.drop_table("ragent_demo_usage")
