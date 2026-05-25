"""Pydantic request/response models for auth endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from promptforge_api.models import OrgRole


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)
    org_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str | None
    created_at: datetime


class OrgResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str


class MembershipSummary(BaseModel):
    org: OrgResponse
    role: OrgRole


class AuthSuccessResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    org: OrgResponse
    role: OrgRole


class AccessOnlyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user: UserResponse
    memberships: list[MembershipSummary]
    current_org_id: UUID
    role: OrgRole


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ApiKeyCreateResponse(BaseModel):
    """Response on creation; `key` is shown exactly once."""

    id: UUID
    name: str
    prefix: str
    key: str
    created_at: datetime


class ApiKeyListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    prefix: str
    last_used_at: datetime | None
    created_at: datetime
