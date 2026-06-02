"""Pydantic response models for demo-mode endpoints."""

from pydantic import BaseModel

from promptforge_api.models import OrgRole
from promptforge_api.schemas.auth import OrgResponse, UserResponse


class DemoLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    org: OrgResponse
    role: OrgRole
    free_runs_remaining: int


class DemoQuotaResponse(BaseModel):
    limit: int
    used: int
    remaining: int
