"""add share_tokens table

Revision ID: 20260602_0008
Revises: 20260601_0007
Create Date: 2026-06-02
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260602_0008"
down_revision: str | None = "20260601_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    resource_type_enum = postgresql.ENUM("prompt", "eval_batch", name="share_resource_type")

    op.create_table(
        "share_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", resource_type_enum, nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hmac", sa.String(length=128), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name="fk_share_tokens_org_id_orgs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_share_tokens_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_share_tokens"),
        sa.UniqueConstraint("token_hmac", name="uq_share_tokens_token_hmac"),
    )
    op.create_index("ix_share_tokens_org_id", "share_tokens", ["org_id"])
    op.create_index("ix_share_tokens_resource_id", "share_tokens", ["resource_id"])


def downgrade() -> None:
    op.drop_index("ix_share_tokens_resource_id", table_name="share_tokens")
    op.drop_index("ix_share_tokens_org_id", table_name="share_tokens")
    op.drop_table("share_tokens")
    postgresql.ENUM(name="share_resource_type").drop(op.get_bind(), checkfirst=True)
