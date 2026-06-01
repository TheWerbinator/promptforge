"""add eval suites, cases, batches, results

Revision ID: 20260601_0006
Revises: 20260529_0005
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260601_0006"
down_revision: str | None = "20260529_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ENUMs are created implicitly when first referenced by a column.
    judge_enum = postgresql.ENUM("exact", "contains", "regex", "llm_judge", name="judge_kind")
    batch_status_enum = postgresql.ENUM(
        "queued", "running", "done", "failed", name="eval_batch_status"
    )

    op.create_table(
        "eval_suites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("judge_default", judge_enum, nullable=False, server_default="exact"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
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
            ["org_id"], ["orgs.id"], name="fk_eval_suites_org_id_orgs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_eval_suites_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_suites"),
        sa.UniqueConstraint("org_id", "name", name="uq_eval_suites_org_name"),
    )
    op.create_index("ix_eval_suites_org_id", "eval_suites", ["org_id"])

    op.create_table(
        "eval_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "expected",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("judge", judge_enum, nullable=True),
        sa.Column(
            "judge_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
            ["suite_id"],
            ["eval_suites.id"],
            name="fk_eval_cases_suite_id_eval_suites",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_cases"),
    )
    op.create_index("ix_eval_cases_suite_id", "eval_cases", ["suite_id"])

    op.create_table(
        "eval_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "version_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "status",
            batch_status_enum,
            nullable=False,
            server_default="queued",
        ),
        sa.Column("total_jobs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_jobs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
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
            ["org_id"], ["orgs.id"], name="fk_eval_batches_org_id_orgs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["eval_suites.id"],
            name="fk_eval_batches_suite_id_eval_suites",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_eval_batches_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_batches"),
    )
    op.create_index("ix_eval_batches_org_id", "eval_batches", ["org_id"])
    op.create_index("ix_eval_batches_suite_id", "eval_batches", ["suite_id"])

    op.create_table(
        "eval_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("judge_reasoning", sa.Text(), nullable=True),
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
            ["batch_id"],
            ["eval_batches.id"],
            name="fk_eval_results_batch_id_eval_batches",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["prompt_versions.id"],
            name="fk_eval_results_version_id_prompt_versions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["eval_cases.id"],
            name="fk_eval_results_case_id_eval_cases",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name="fk_eval_results_run_id_runs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_results"),
        sa.UniqueConstraint(
            "batch_id",
            "version_id",
            "case_id",
            name="uq_eval_results_batch_version_case",
        ),
    )
    op.create_index("ix_eval_results_batch_id", "eval_results", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_eval_results_batch_id", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("ix_eval_batches_suite_id", table_name="eval_batches")
    op.drop_index("ix_eval_batches_org_id", table_name="eval_batches")
    op.drop_table("eval_batches")
    op.drop_index("ix_eval_cases_suite_id", table_name="eval_cases")
    op.drop_table("eval_cases")
    op.drop_index("ix_eval_suites_org_id", table_name="eval_suites")
    op.drop_table("eval_suites")
    postgresql.ENUM(name="eval_batch_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="judge_kind").drop(op.get_bind(), checkfirst=True)
