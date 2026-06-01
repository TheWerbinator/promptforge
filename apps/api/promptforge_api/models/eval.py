"""Eval models — suites, cases, batches, and results.

An EvalSuite is a named collection of EvalCases. Running it produces an EvalBatch
across one or more PromptVersions, which fans out to (cases x versions) jobs on
the Postgres queue. Each job produces one Run row + one EvalResult row.

Tenancy: EvalSuite and EvalBatch carry `org_id` directly (TenantRepository
scopes them). EvalCase is scoped via its suite; EvalResult via its batch.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    pass


class JudgeKind(StrEnum):
    EXACT = "exact"
    CONTAINS = "contains"
    REGEX = "regex"
    LLM_JUDGE = "llm_judge"


class EvalBatchStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


_JUDGE_ENUM = SqlEnum(
    JudgeKind,
    name="judge_kind",
    native_enum=True,
    values_callable=lambda e: [m.value for m in e],
)
_BATCH_STATUS_ENUM = SqlEnum(
    EvalBatchStatus,
    name="eval_batch_status",
    native_enum=True,
    values_callable=lambda e: [m.value for m in e],
)


class EvalSuite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "eval_suites"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_eval_suites_org_name"),)

    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    judge_default: Mapped[JudgeKind] = mapped_column(
        _JUDGE_ENUM, nullable=False, default=JudgeKind.EXACT
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    cases: Mapped[list["EvalCase"]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class EvalCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "eval_cases"

    suite_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("eval_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # `expected` shape depends on the judge:
    #   exact / contains / regex → {"value": "..."}
    #   llm_judge → {"rubric": "...", "criterion": "..."}
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Per-case judge override; if NULL, falls back to suite.judge_default.
    judge: Mapped[JudgeKind | None] = mapped_column(_JUDGE_ENUM, nullable=True)
    # Optional per-case judge config (e.g. case_sensitive for contains).
    judge_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    suite: Mapped[EvalSuite] = relationship(back_populates="cases")


class EvalBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "eval_batches"

    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suite_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("eval_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Which PromptVersion IDs this batch is evaluating.
    version_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[EvalBatchStatus] = mapped_column(
        _BATCH_STATUS_ENUM, nullable=False, default=EvalBatchStatus.QUEUED
    )
    total_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class EvalResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "eval_results"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "version_id", "case_id", name="uq_eval_results_batch_version_case"
        ),
    )

    batch_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("eval_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("eval_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The Run that produced the output being judged. Nullable: a run that
    # failed to even produce an output still gets an EvalResult row marked
    # passed=False so dashboards see the failure.
    run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    judge_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
