"""Pydantic models for share tokens.

Two audiences:
- owner-facing: create/list share tokens (`ShareCreate`, `ShareTokenResponse`,
  `ShareTokenListItem`). The plaintext token is returned once, on create.
- public: the read-only views served at `/public/share/{token}`. These are
  deliberately minimal — no org_id, no created_by, no provider_response — so a
  share link exposes the artifact and nothing about the workspace behind it.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promptforge_api.models import EvalBatchStatus, ShareResourceType


class ShareCreate(BaseModel):
    resource_type: ShareResourceType
    resource_id: UUID
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class ShareTokenResponse(BaseModel):
    """Returned on create. `token` is shown exactly once."""

    id: UUID
    resource_type: ShareResourceType
    resource_id: UUID
    token: str
    expires_at: datetime | None
    created_at: datetime


class ShareTokenListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resource_type: ShareResourceType
    resource_id: UUID
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


# ----- public read-only views -----------------------------------------------------------


class PublicPromptVersion(BaseModel):
    version: int
    body: str
    variables: list[dict[str, Any]]


class PublicPromptShare(BaseModel):
    name: str
    description: str | None
    latest_version: PublicPromptVersion | None
    updated_at: datetime


class PublicEvalResult(BaseModel):
    version_id: str
    inputs: dict[str, Any]
    expected: dict[str, Any]
    score: float
    passed: bool
    judge_reasoning: str | None


class PublicEvalBatchShare(BaseModel):
    suite_name: str
    status: EvalBatchStatus
    total_jobs: int
    completed_jobs: int
    pass_rate: float
    results: list[PublicEvalResult]


class PublicShareResponse(BaseModel):
    resource_type: ShareResourceType
    prompt: PublicPromptShare | None = None
    eval_batch: PublicEvalBatchShare | None = None
