"""Pydantic request/response models for runs."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RunRequest(BaseModel):
    model: str = Field(min_length=1, max_length=120)
    inputs: dict[str, Any] = Field(default_factory=dict)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    version_id: UUID
    model: str
    inputs: dict[str, Any]
    output: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    latency_ms: int
    error: str | None
    created_at: datetime


class RunListResponse(BaseModel):
    items: list[RunResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
