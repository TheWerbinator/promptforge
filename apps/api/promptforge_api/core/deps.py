"""FastAPI dependencies: Principal extraction, role gates."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.core.db import get_session
from promptforge_api.core.security import (
    InvalidTokenError,
    decode_access_token,
    parse_api_key_prefix,
    verify_api_key,
)
from promptforge_api.models import ApiKey, OrgRole

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    org_id: UUID
    role: OrgRole
    auth: Literal["jwt", "api_key"]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _principal_from_api_key(plain_key: str, prefix: str, session: AsyncSession) -> Principal:
    result = await session.execute(
        select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None))
    )
    for key in result.scalars():
        if verify_api_key(plain_key, key.key_hash):
            return Principal(
                user_id=key.user_id,
                org_id=key.org_id,
                role=OrgRole.MEMBER,
                auth="api_key",
            )
    raise _unauthorized("invalid api key")


async def get_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    if creds is None or not creds.credentials:
        raise _unauthorized("missing credentials")

    token = creds.credentials

    prefix = parse_api_key_prefix(token)
    if prefix is not None:
        return await _principal_from_api_key(token, prefix, session)

    try:
        payload = decode_access_token(token)
    except InvalidTokenError as exc:
        raise _unauthorized("invalid token") from exc

    try:
        role = OrgRole(payload.role)
    except ValueError as exc:
        raise _unauthorized("invalid role claim") from exc

    return Principal(
        user_id=UUID(payload.sub),
        org_id=UUID(payload.org),
        role=role,
        auth="jwt",
    )


def require_role(
    *allowed: OrgRole,
) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency factory: 403 if principal's role isn't in `allowed`."""

    async def _check(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient role",
            )
        return principal

    return _check
