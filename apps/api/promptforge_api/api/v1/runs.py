"""POST /versions/{id}/run and GET /runs/{id}.

Run lives in its own router (not nested under prompts) because the `runs/{id}`
GET is the natural detail URL — embedding it under prompts would mean callers
need a prompt id they don't necessarily have.

Tenancy for POST: resolved through the parent prompt (same pattern as the
version GET in api/v1/versions.py). Tenancy for the runs GET: TenantRepository.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.api.v1.prompts import _resolve_prompt_for_principal
from promptforge_api.core.config import get_settings
from promptforge_api.core.db import get_session
from promptforge_api.core.deps import Principal, get_principal, get_repo
from promptforge_api.core.prompts import (
    PromptTemplate,
    PromptValidationError,
    PromptVariable,
)
from promptforge_api.core.ratelimit import client_ip
from promptforge_api.models import OrgRole, Prompt, PromptVersion, Run
from promptforge_api.repositories import TenantRepository
from promptforge_api.schemas.run import RunRequest, RunResponse
from promptforge_api.services import demo as demo_service
from promptforge_api.services import llm as llm_service

versions_router = APIRouter(prefix="/versions", tags=["runs"])
runs_router = APIRouter(prefix="/runs", tags=["runs"])


@versions_router.post(
    "/{version_id}/run",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def run_version(
    version_id: UUID,
    body: RunRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    prompt_repo: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
    run_repo: TenantRepository[Run] = Depends(get_repo(Run)),
    session: AsyncSession = Depends(get_session),
    x_provider_key: Annotated[str | None, Header()] = None,
) -> RunResponse:
    version = await session.get(PromptVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")
    await _resolve_prompt_for_principal(version.prompt_id, principal, prompt_repo)

    # Demo free-taste: a demo visitor without their own key gets a few real runs
    # on the hosted key (per IP per day) before we ask them to bring their own.
    # BYOK callers skip the quota entirely — it's their key and their bill.
    demo_ip_hash: str | None = None
    if principal.role is OrgRole.DEMO and not x_provider_key:
        settings = get_settings()
        demo_ip_hash = demo_service.ip_hash(client_ip(request))
        remaining = await demo_service.free_runs_remaining(
            session, demo_ip_hash, limit=settings.demo_free_runs
        )
        if remaining <= 0:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"You've used all {settings.demo_free_runs} free demo runs for today. "
                    "Add your own provider key via the X-Provider-Key header to keep going."
                ),
            )

    template = PromptTemplate(
        body=version.body,
        variables=[PromptVariable(**v) for v in version.variables],
    )
    try:
        rendered = template.render(**body.inputs)
    except PromptValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": exc.errors},
        ) from exc

    messages = [{"role": "user", "content": rendered}]

    output: str | None = None
    error: str | None = None
    input_tokens = output_tokens = latency_ms = 0
    cost_usd: float | None = None
    provider_response: dict[str, Any] | None = None

    try:
        result = await llm_service.call_llm(
            body.model,
            messages,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            user_api_key=x_provider_key,
        )
        output = result.text
        input_tokens = result.input_tokens
        output_tokens = result.output_tokens
        cost_usd = result.cost_usd
        latency_ms = result.latency_ms
        provider_response = result.provider_response
    except llm_service.LLMCallError as exc:
        # Persist failed runs too — dashboards need them for error-rate metrics.
        error = str(exc)

    # Use the version's prompt's org for the Run's org_id. TenantRepository.add
    # would default org_id to principal.org_id; the prompt resolve above already
    # confirmed they match, so we just pass it through.
    run = await run_repo.add(
        version_id=version.id,
        model=body.model,
        inputs=body.inputs,
        output=output,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        provider_response=provider_response,
        error=error,
        created_by=principal.user_id,
    )

    # Only count a free demo run when the hosted call actually succeeded — a
    # failure on our key shouldn't eat the visitor's taste.
    if demo_ip_hash is not None and error is None:
        await demo_service.record_free_run(session, demo_ip_hash)

    return RunResponse.model_validate(run)


@runs_router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    repo: TenantRepository[Run] = Depends(get_repo(Run)),
) -> RunResponse:
    run = await repo.get_or_404(run_id)
    return RunResponse.model_validate(run)
