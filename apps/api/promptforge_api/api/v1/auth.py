"""Auth endpoints: signup, login, refresh, logout, /me, api-keys CRUD."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.core.config import get_settings
from promptforge_api.core.db import get_session
from promptforge_api.core.deps import Principal, get_principal, get_repo
from promptforge_api.core.security import (
    create_access_token,
    generate_api_key,
    generate_refresh_token,
    hash_password,
    hmac_token,
    verify_password,
)
from promptforge_api.models import ApiKey, Membership, Org, OrgRole, RefreshToken, User
from promptforge_api.repositories import TenantRepository
from promptforge_api.schemas.auth import (
    AccessOnlyResponse,
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListItem,
    AuthSuccessResponse,
    LoginRequest,
    MembershipSummary,
    MeResponse,
    OrgResponse,
    SignupRequest,
    UserResponse,
)

REFRESH_COOKIE: Final = "pf_refresh"
REFRESH_COOKIE_PATH: Final = "/api/v1/auth"

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Lowercase, ASCII-only, dash-separated. Suffixed elsewhere for uniqueness."""
    nfkd = unicodedata.normalize("NFKD", value)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "org"


async def _unique_slug(session: AsyncSession, base: str) -> str:
    slug = base[:56]  # leave room for suffix; column is varchar(64)
    candidate = slug
    suffix = 1
    while True:
        existing = await session.execute(select(Org.id).where(Org.slug == candidate))
        if existing.first() is None:
            return candidate
        suffix += 1
        candidate = f"{slug}-{suffix}"


def _set_refresh_cookie(response: Response, plain: str, max_age_seconds: int) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=plain,
        max_age=max_age_seconds,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
    )


async def _issue_session(
    session: AsyncSession,
    response: Response,
    *,
    user: User,
    org: Org,
    role: OrgRole,
    chain_id: UUID | None = None,
    parent_id: UUID | None = None,
) -> str:
    """Create a refresh token row, set the cookie, return an access token."""
    settings = get_settings()
    plain, hmac_hex = generate_refresh_token()
    now = datetime.now(UTC)
    refresh = RefreshToken(
        user_id=user.id,
        org_id=org.id,
        chain_id=chain_id or uuid4(),
        token_hmac=hmac_hex,
        parent_id=parent_id,
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
    )
    session.add(refresh)
    await session.flush()

    _set_refresh_cookie(
        response,
        plain,
        max_age_seconds=settings.refresh_token_ttl_days * 24 * 3600,
    )

    return create_access_token(user_id=user.id, org_id=org.id, role=role.value)


# --------------------------------------------------------------------------------------
# Signup / login / me
# --------------------------------------------------------------------------------------


@router.post(
    "/signup",
    response_model=AuthSuccessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(
    body: SignupRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> AuthSuccessResponse:
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    session.add(user)

    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already in use"
        ) from exc

    org_name = body.org_name or (
        f"{body.display_name}'s Workspace"
        if body.display_name
        else f"{body.email.split('@')[0]}'s Workspace"
    )
    org_slug = await _unique_slug(session, _slugify(org_name))
    org = Org(name=org_name, slug=org_slug)
    session.add(org)
    await session.flush()

    session.add(Membership(user_id=user.id, org_id=org.id, role=OrgRole.OWNER))
    await session.flush()

    access = await _issue_session(session, response, user=user, org=org, role=OrgRole.OWNER)

    return AuthSuccessResponse(
        access_token=access,
        user=UserResponse.model_validate(user),
        org=OrgResponse.model_validate(org),
        role=OrgRole.OWNER,
    )


@router.post("/login", response_model=AuthSuccessResponse)
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> AuthSuccessResponse:
    result = await session.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise _INVALID_CREDENTIALS

    # Pick the user's owner-most membership (owner > member > demo).
    role_priority = {OrgRole.OWNER: 0, OrgRole.MEMBER: 1, OrgRole.DEMO: 2}
    if not user.memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="no active org membership"
        )
    membership = sorted(user.memberships, key=lambda m: role_priority[m.role])[0]
    org = membership.org

    access = await _issue_session(session, response, user=user, org=org, role=membership.role)

    return AuthSuccessResponse(
        access_token=access,
        user=UserResponse.model_validate(user),
        org=OrgResponse.model_validate(org),
        role=membership.role,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> MeResponse:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    memberships = [
        MembershipSummary(org=OrgResponse.model_validate(m.org), role=m.role)
        for m in user.memberships
    ]
    return MeResponse(
        user=UserResponse.model_validate(user),
        memberships=memberships,
        current_org_id=principal.org_id,
        role=principal.role,
    )


# --------------------------------------------------------------------------------------
# Refresh / logout
# --------------------------------------------------------------------------------------


async def _revoke_chain(session: AsyncSession, chain_id: UUID) -> None:
    now = datetime.now(UTC)
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.chain_id == chain_id, RefreshToken.revoked_at.is_(None)
        )
    )
    for row in result.scalars():
        row.revoked_at = now


@router.post("/refresh", response_model=AccessOnlyResponse)
async def refresh(
    response: Response,
    pf_refresh: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> AccessOnlyResponse:
    if not pf_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing refresh token")

    hmac_hex = hmac_token(pf_refresh)
    result = await session.execute(select(RefreshToken).where(RefreshToken.token_hmac == hmac_hex))
    token = result.scalar_one_or_none()

    if token is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")

    now = datetime.now(UTC)

    # Replay defense: token already rotated or revoked → kill entire chain.
    # Commit the revocation before raising so the session rollback in get_session
    # doesn't undo it.
    if token.revoked_at is not None or token.replaced_at is not None:
        await _revoke_chain(session, token.chain_id)
        await session.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="refresh token replay detected")

    if token.expires_at <= now:
        token.revoked_at = now
        await session.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="refresh token expired")

    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        await _revoke_chain(session, token.chain_id)
        await session.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="account unavailable")

    membership = next(
        (m for m in user.memberships if m.org_id == token.org_id),
        None,
    )
    if membership is None:
        await _revoke_chain(session, token.chain_id)
        await session.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="membership revoked")

    org = membership.org
    token.replaced_at = now

    access = await _issue_session(
        session,
        response,
        user=user,
        org=org,
        role=membership.role,
        chain_id=token.chain_id,
        parent_id=token.id,
    )

    return AccessOnlyResponse(access_token=access)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    pf_refresh: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if pf_refresh:
        hmac_hex = hmac_token(pf_refresh)
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hmac == hmac_hex)
        )
        token = result.scalar_one_or_none()
        if token is not None:
            await _revoke_chain(session, token.chain_id)
    _clear_refresh_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------------------
# API keys
# --------------------------------------------------------------------------------------


@router.post(
    "/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    body: ApiKeyCreateRequest,
    principal: Principal = Depends(get_principal),
    repo: TenantRepository[ApiKey] = Depends(get_repo(ApiKey)),
) -> ApiKeyCreateResponse:
    if principal.auth != "jwt":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="api keys can only be issued via an authenticated session",
        )

    plain, prefix, key_hash = generate_api_key()
    row = await repo.add(
        user_id=principal.user_id,
        name=body.name,
        key_hash=key_hash,
        prefix=prefix,
    )
    return ApiKeyCreateResponse(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        key=plain,
        created_at=row.created_at,
    )


@router.get("/api-keys", response_model=list[ApiKeyListItem])
async def list_api_keys(
    repo: TenantRepository[ApiKey] = Depends(get_repo(ApiKey)),
) -> list[ApiKeyListItem]:
    rows = await repo.list(limit=200, order_by=ApiKey.created_at.desc())
    return [ApiKeyListItem.model_validate(r) for r in rows if r.revoked_at is None]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: UUID,
    repo: TenantRepository[ApiKey] = Depends(get_repo(ApiKey)),
) -> Response:
    row = await repo.get(key_id)
    if row is None or row.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="api key not found")
    row.revoked_at = datetime.now(UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
