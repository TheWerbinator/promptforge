"""FastAPI dependencies: the authenticated Principal."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from promptforge_ragent.core.security import InvalidTokenError, decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    org_id: UUID
    role: str


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if creds is None or not creds.credentials:
        raise _unauthorized("missing credentials")
    try:
        payload = decode_access_token(creds.credentials)
    except InvalidTokenError as exc:
        raise _unauthorized("invalid token") from exc
    return Principal(
        user_id=UUID(payload.sub),
        org_id=UUID(payload.org),
        role=payload.role,
    )
