"""Direct version access by version_id.

Listing versions of a specific prompt lives under /prompts/{id}/versions in
api/v1/prompts.py. This file exposes a single-version GET that resolves a
version through its parent prompt for tenancy + visibility enforcement.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.api.v1.prompts import _resolve_prompt_for_principal
from promptforge_api.core.db import get_session
from promptforge_api.core.deps import Principal, get_principal, get_repo
from promptforge_api.models import Prompt, PromptVersion
from promptforge_api.repositories import TenantRepository
from promptforge_api.schemas.prompt import PromptVersionResponse

router = APIRouter(prefix="/versions", tags=["versions"])


@router.get("/{version_id}", response_model=PromptVersionResponse)
async def get_version(
    version_id: UUID,
    principal: Principal = Depends(get_principal),
    repo: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
    session: AsyncSession = Depends(get_session),
) -> PromptVersionResponse:
    version = await session.get(PromptVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")

    # Resolve the parent prompt via the tenancy-aware path. If the prompt is in
    # another org (or a private prompt belonging to another user), the helper
    # raises 404 and we never confirm the version exists.
    await _resolve_prompt_for_principal(version.prompt_id, principal, repo)
    return PromptVersionResponse.model_validate(version)
