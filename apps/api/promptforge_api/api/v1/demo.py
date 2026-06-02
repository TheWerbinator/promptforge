"""Demo mode: instant read-only access to the seeded Demo Corp workspace.

`POST /demo/login` mints a demo session (role=demo) for the shared seeded demo
account — no signup, no password. The session is read-only everywhere except the
single-prompt run route, which grants a small free hosted-key quota before asking
the visitor to bring their own provider key (see api/v1/runs.py).

`GET /demo/quota` lets the UI show "N free runs left" for the visitor's IP.

The login route is rate-limited (slowapi) so the endpoint that creates sessions
+ refresh-token rows can't be hammered into a cheap DoS.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.api.v1.auth import _issue_session
from promptforge_api.core.config import get_settings
from promptforge_api.core.db import get_session
from promptforge_api.core.deps import Principal, require_role
from promptforge_api.core.ratelimit import client_ip, limiter
from promptforge_api.models import OrgRole, User
from promptforge_api.schemas.auth import OrgResponse, UserResponse
from promptforge_api.schemas.demo import DemoLoginResponse, DemoQuotaResponse
from promptforge_api.services import demo as demo_service

router = APIRouter(prefix="/demo", tags=["demo"])

require_demo = require_role(OrgRole.DEMO)


def _demo_rate_limit() -> str:
    # Callable so the limit is read per-request from settings, not frozen at
    # import time (keeps test config + env overrides honest).
    return get_settings().demo_rate_limit


@router.post("/login", response_model=DemoLoginResponse)
@limiter.limit(_demo_rate_limit)
async def demo_login(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> DemoLoginResponse:
    settings = get_settings()
    user = (
        await session.execute(select(User).where(User.email == settings.demo_email))
    ).scalar_one_or_none()
    membership = (
        next((m for m in user.memberships if m.role is OrgRole.DEMO), None) if user else None
    )
    if user is None or membership is None or not user.is_active:
        # Seed hasn't run (phase 15) or demo was disabled. 503, not 404 — the
        # route exists; the backing account is just unavailable right now.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="demo account is not configured",
        )

    org = membership.org
    access = await _issue_session(session, response, user=user, org=org, role=OrgRole.DEMO)
    return DemoLoginResponse(
        access_token=access,
        user=UserResponse.model_validate(user),
        org=OrgResponse.model_validate(org),
        role=OrgRole.DEMO,
        free_runs_remaining=await demo_service.free_runs_remaining(
            session,
            demo_service.ip_hash(client_ip(request)),
            limit=settings.demo_free_runs,
        ),
    )


@router.get("/quota", response_model=DemoQuotaResponse)
async def demo_quota(
    request: Request,
    _: Principal = Depends(require_demo),
    session: AsyncSession = Depends(get_session),
) -> DemoQuotaResponse:
    settings = get_settings()
    remaining = await demo_service.free_runs_remaining(
        session,
        demo_service.ip_hash(client_ip(request)),
        limit=settings.demo_free_runs,
    )
    return DemoQuotaResponse(
        limit=settings.demo_free_runs,
        remaining=remaining,
        used=settings.demo_free_runs - remaining,
    )
