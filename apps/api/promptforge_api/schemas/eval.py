"""Pydantic request/response models for eval endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promptforge_api.models import EvalBatchStatus, JudgeKind


class EvalSuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    judge_default: JudgeKind = JudgeKind.EXACT


class EvalCaseCreate(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    judge: JudgeKind | None = None
    judge_config: dict[str, Any] = Field(default_factory=dict)


class EvalBatchRunRequest(BaseModel):
    version_ids: list[UUID] = Field(min_length=1, max_length=20)


class EvalSuiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    description: str | None
    judge_default: JudgeKind
    created_at: datetime


class EvalCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    suite_id: UUID
    inputs: dict[str, Any]
    expected: dict[str, Any]
    judge: JudgeKind | None
    judge_config: dict[str, Any]
    created_at: datetime


class EvalBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    suite_id: UUID
    version_ids: list[str]
    status: EvalBatchStatus
    total_jobs: int
    completed_jobs: int
    created_at: datetime


class EvalResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    version_id: UUID
    case_id: UUID
    run_id: UUID | None
    score: float
    passed: bool
    judge_reasoning: str | None


class EvalBatchDetailResponse(EvalBatchResponse):
    results: list[EvalResultResponse]
