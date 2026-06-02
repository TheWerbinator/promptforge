"""Share tokens: owner-facing CRUD + the public read-only endpoint.

  POST   /api/v1/shares              create a share link (writer only)
  GET    /api/v1/shares              list this org's share links
  DELETE /api/v1/shares/{id}         revoke a link
  GET    /api/v1/public/share/{token}   resolve a link (no auth) -> read-only view

The public route is the only unauthenticated read in the API. It hashes the
incoming token, looks the row up by digest, rejects revoked/expired tokens, then
resolves the target resource and returns a minimal public projection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.core.db import get_session
from promptforge_api.core.deps import Principal, get_repo, require_writer
from promptforge_api.core.security import generate_share_token, hmac_token
from promptforge_api.models import (
    EvalBatch,
    EvalCase,
    EvalResult,
    EvalSuite,
    Prompt,
    PromptVersion,
    ShareResourceType,
    ShareToken,
)
from promptforge_api.repositories import TenantRepository
from promptforge_api.schemas.share import (
    PublicEvalBatchShare,
    PublicEvalResult,
    PublicPromptShare,
    PublicPromptVersion,
    PublicShareResponse,
    ShareCreate,
    ShareTokenListItem,
    ShareTokenResponse,
)

shares_router = APIRouter(prefix="/shares", tags=["shares"])
public_router = APIRouter(prefix="/public", tags=["public"])


@shares_router.post("", response_model=ShareTokenResponse, status_code=status.HTTP_201_CREATED)
async def create_share(
    body: ShareCreate,
    principal: Principal = Depends(require_writer),
    shares: TenantRepository[ShareToken] = Depends(get_repo(ShareToken)),
    prompts: TenantRepository[Prompt] = Depends(get_repo(Prompt)),
    batches: TenantRepository[EvalBatch] = Depends(get_repo(EvalBatch)),
) -> ShareTokenResponse:
    # Confirm the resource exists in the caller's org before minting a token —
    # cross-org or unknown ids 404 via the tenant repo.
    if body.resource_type is ShareResourceType.PROMPT:
        await prompts.get_or_404(body.resource_id)
    else:
        await batches.get_or_404(body.resource_id)

    plain, token_hmac = generate_share_token()
    expires_at = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None
        else None
    )
    row = await shares.add(
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        token_hmac=token_hmac,
        created_by=principal.user_id,
        expires_at=expires_at,
    )
    return ShareTokenResponse(
        id=row.id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        token=plain,
        expires_at=row.expires_at,
        created_at=row.created_at,
    )


@shares_router.get("", response_model=list[ShareTokenListItem])
async def list_shares(
    shares: TenantRepository[ShareToken] = Depends(get_repo(ShareToken)),
) -> list[ShareTokenListItem]:
    rows = await shares.list(limit=200, order_by=ShareToken.created_at.desc())
    return [ShareTokenListItem.model_validate(r) for r in rows]


@shares_router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    share_id: UUID,
    _writer: Principal = Depends(require_writer),
    shares: TenantRepository[ShareToken] = Depends(get_repo(ShareToken)),
) -> Response:
    row = await shares.get(share_id)
    if row is None or row.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="share not found")
    row.revoked_at = datetime.now(UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_SHARE_GONE = HTTPException(status.HTTP_404_NOT_FOUND, detail="share link not found or expired")


@public_router.get("/share/{token}", response_model=PublicShareResponse)
async def resolve_share(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> PublicShareResponse:
    share = (
        await session.execute(select(ShareToken).where(ShareToken.token_hmac == hmac_token(token)))
    ).scalar_one_or_none()
    if share is None or share.revoked_at is not None:
        raise _SHARE_GONE
    if share.expires_at is not None and share.expires_at <= datetime.now(UTC):
        raise _SHARE_GONE

    if share.resource_type is ShareResourceType.PROMPT:
        prompt_view = await _build_prompt_share(session, share.resource_id)
        if prompt_view is None:
            raise _SHARE_GONE
        return PublicShareResponse(resource_type=share.resource_type, prompt=prompt_view)

    batch_view = await _build_eval_batch_share(session, share.resource_id)
    if batch_view is None:
        raise _SHARE_GONE
    return PublicShareResponse(resource_type=share.resource_type, eval_batch=batch_view)


async def _build_prompt_share(session: AsyncSession, prompt_id: UUID) -> PublicPromptShare | None:
    prompt = await session.get(Prompt, prompt_id)
    if prompt is None:
        return None
    latest = (
        await session.execute(
            select(PromptVersion)
            .where(PromptVersion.prompt_id == prompt_id)
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return PublicPromptShare(
        name=prompt.name,
        description=prompt.description,
        latest_version=(
            PublicPromptVersion(
                version=latest.version, body=latest.body, variables=latest.variables
            )
            if latest is not None
            else None
        ),
        updated_at=prompt.updated_at,
    )


async def _build_eval_batch_share(
    session: AsyncSession, batch_id: UUID
) -> PublicEvalBatchShare | None:
    batch = await session.get(EvalBatch, batch_id)
    if batch is None:
        return None
    suite = await session.get(EvalSuite, batch.suite_id)
    cases = {
        c.id: c
        for c in (
            await session.execute(select(EvalCase).where(EvalCase.suite_id == batch.suite_id))
        ).scalars()
    }
    results = list(
        (await session.execute(select(EvalResult).where(EvalResult.batch_id == batch_id))).scalars()
    )
    public_results = [
        PublicEvalResult(
            version_id=str(r.version_id),
            inputs=cases[r.case_id].inputs if r.case_id in cases else {},
            expected=cases[r.case_id].expected if r.case_id in cases else {},
            score=r.score,
            passed=r.passed,
            judge_reasoning=r.judge_reasoning,
        )
        for r in results
    ]
    passed = sum(1 for r in results if r.passed)
    return PublicEvalBatchShare(
        suite_name=suite.name if suite is not None else "(deleted suite)",
        status=batch.status,
        total_jobs=batch.total_jobs,
        completed_jobs=batch.completed_jobs,
        pass_rate=(passed / len(results)) if results else 0.0,
        results=public_results,
    )
