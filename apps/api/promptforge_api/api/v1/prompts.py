"""Prompt CRUD + version creation/listing routes.

Visibility is enforced at the route layer:
- PRIVATE prompts: visible only to their creator within the org.
- ORG / PUBLIC: visible to every org member.
PUBLIC is currently a marker only; the share-link surface lands in phase 14.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.core.db import get_session
from promptforge_api.core.deps import Principal, get_principal, get_repo, require_writer
from promptforge_api.core.prompts import PromptTemplate, PromptVariable
from promptforge_api.models import Prompt, PromptVersion, PromptVisibility
from promptforge_api.repositories import TenantRepository
from promptforge_api.schemas.prompt import (
    PromptCreate,
    PromptDetailResponse,
    PromptListResponse,
    PromptResponse,
    PromptUpdate,
    PromptVersionCreate,
    PromptVersionResponse,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _visibility_filter(principal: Principal) -> ColumnElement[bool]:
    """Hides PRIVATE prompts that don't belong to the current user."""
    return or_(
        Prompt.visibility != PromptVisibility.PRIVATE,
        Prompt.created_by == principal.user_id,
    )


def _validate_template(body: str, variables: list[dict[str, Any]]) -> None:
    """422 if the body/variables don't form a valid PromptTemplate."""
    try:
        PromptTemplate(
            body=body,
            variables=[PromptVariable(**v) for v in variables],
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid prompt template: {exc.errors()}",
        ) from exc


async def _resolve_prompt_for_principal(
    prompt_id: UUID,
    principal: Principal,
    repo: TenantRepository[Prompt],
) -> Prompt:
    prompt = await repo.get(prompt_id)
    if prompt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="prompt not found")
    if prompt.visibility == PromptVisibility.PRIVATE and prompt.created_by != principal.user_id:
        # Same 404 — never leak existence of another user's private prompt.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="prompt not found")
    return prompt


async def _latest_version(session: AsyncSession, prompt_id: UUID) -> PromptVersion | None:
    stmt = (
        select(PromptVersion)
        .where(PromptVersion.prompt_id == prompt_id)
        .order_by(PromptVersion.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _next_version_number(session: AsyncSession, prompt_id: UUID) -> int:
    stmt = select(func.max(PromptVersion.version)).where(PromptVersion.prompt_id == prompt_id)
    current = (await session.execute(stmt)).scalar_one()
    return (current or 0) + 1


@router.post(
    "",
    response_model=PromptDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt(
    body: PromptCreate,
    principal: Principal = Depends(require_writer),
    repo: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
    session: AsyncSession = Depends(get_session),
) -> PromptDetailResponse:
    _validate_template(body.body, body.variables)
    try:
        prompt = await repo.add(
            name=body.name,
            description=body.description,
            tags=body.tags,
            visibility=body.visibility,
            created_by=principal.user_id,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="prompt name already in use within this org",
        ) from exc

    v1 = PromptVersion(
        prompt_id=prompt.id,
        version=1,
        body=body.body,
        variables=body.variables,
        created_by=principal.user_id,
    )
    session.add(v1)
    await session.flush()

    return PromptDetailResponse(
        **PromptResponse.model_validate(prompt).model_dump(),
        latest_version=PromptVersionResponse.model_validate(v1),
    )


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    principal: Principal = Depends(get_principal),
    repo: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
    q: Annotated[str | None, Query(max_length=200)] = None,
    tag: Annotated[str | None, Query(max_length=64)] = None,
    visibility: PromptVisibility | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> PromptListResponse:
    where = _visibility_filter(principal)
    if q:
        ilike = f"%{q}%"
        where = where & (Prompt.name.ilike(ilike) | Prompt.description.ilike(ilike))
    if tag:
        where = where & Prompt.tags.contains([tag])
    if visibility is not None:
        where = where & (Prompt.visibility == visibility)

    offset = (page - 1) * page_size
    items = await repo.list(
        offset=offset,
        limit=page_size,
        where=where,
        order_by=Prompt.updated_at.desc(),
    )
    total = await repo.count(where=where)

    return PromptListResponse(
        items=[PromptResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + len(items) < total,
    )


@router.get("/{prompt_id}", response_model=PromptDetailResponse)
async def get_prompt(
    prompt_id: UUID,
    principal: Principal = Depends(get_principal),
    repo: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
    session: AsyncSession = Depends(get_session),
) -> PromptDetailResponse:
    prompt = await _resolve_prompt_for_principal(prompt_id, principal, repo)
    latest = await _latest_version(session, prompt.id)
    return PromptDetailResponse(
        **PromptResponse.model_validate(prompt).model_dump(),
        latest_version=(PromptVersionResponse.model_validate(latest) if latest else None),
    )


@router.patch("/{prompt_id}", response_model=PromptResponse)
async def update_prompt(
    prompt_id: UUID,
    body: PromptUpdate,
    principal: Principal = Depends(require_writer),
    repo: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
) -> PromptResponse:
    prompt = await _resolve_prompt_for_principal(prompt_id, principal, repo)

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return PromptResponse.model_validate(prompt)

    for field, value in fields.items():
        setattr(prompt, field, value)
    prompt.updated_at = datetime.now(UTC)

    try:
        await repo.session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="prompt name already in use within this org",
        ) from exc

    return PromptResponse.model_validate(prompt)


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(
    prompt_id: UUID,
    principal: Principal = Depends(require_writer),
    repo: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
) -> Response:
    prompt = await _resolve_prompt_for_principal(prompt_id, principal, repo)
    await repo.session.delete(prompt)
    await repo.session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{prompt_id}/versions",
    response_model=PromptVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_version(
    prompt_id: UUID,
    body: PromptVersionCreate,
    principal: Principal = Depends(require_writer),
    repo: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
    session: AsyncSession = Depends(get_session),
) -> PromptVersionResponse:
    prompt = await _resolve_prompt_for_principal(prompt_id, principal, repo)
    _validate_template(body.body, body.variables)

    # TODO(phase-5+): wrap next_version_number + insert in a single statement
    # (INSERT ... SELECT max(version)+1) to drop the race window; retry-on-
    # unique-violation is good enough for now since concurrent version creation
    # on the same prompt is rare.
    next_n = await _next_version_number(session, prompt.id)
    version = PromptVersion(
        prompt_id=prompt.id,
        version=next_n,
        body=body.body,
        variables=body.variables,
        created_by=principal.user_id,
    )
    session.add(version)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="concurrent version create; retry",
        ) from exc

    return PromptVersionResponse.model_validate(version)


@router.get(
    "/{prompt_id}/versions",
    response_model=list[PromptVersionResponse],
)
async def list_prompt_versions(
    prompt_id: UUID,
    principal: Principal = Depends(get_principal),
    repo: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
    session: AsyncSession = Depends(get_session),
) -> list[PromptVersionResponse]:
    prompt = await _resolve_prompt_for_principal(prompt_id, principal, repo)
    stmt = (
        select(PromptVersion)
        .where(PromptVersion.prompt_id == prompt.id)
        .order_by(PromptVersion.version.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [PromptVersionResponse.model_validate(r) for r in rows]
