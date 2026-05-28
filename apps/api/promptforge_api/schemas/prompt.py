"""Pydantic request/response models for prompts + versions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promptforge_api.models import PromptVisibility


class PromptVersionCreate(BaseModel):
    body: str = Field(min_length=1, max_length=200_000)
    variables: list[dict[str, Any]] = Field(default_factory=list)


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    visibility: PromptVisibility = PromptVisibility.ORG
    body: str = Field(min_length=1, max_length=200_000)
    variables: list[dict[str, Any]] = Field(default_factory=list)


class PromptUpdate(BaseModel):
    """All fields optional — body lives on versions, not here."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    tags: list[str] | None = Field(default=None, max_length=20)
    visibility: PromptVisibility | None = None


class PromptVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt_id: UUID
    version: int
    body: str
    variables: list[dict[str, Any]]
    created_by: UUID | None
    created_at: datetime


class PromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    description: str | None
    tags: list[str]
    visibility: PromptVisibility
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class PromptDetailResponse(PromptResponse):
    latest_version: PromptVersionResponse | None = None


class PromptListResponse(BaseModel):
    items: list[PromptResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
