"""Access-token decoding.

ragent only ever *validates* tokens (it doesn't issue user sessions), and it does
so with the same HS256 secret apps/api signs them with — so a platform-issued
access token is accepted here directly, no round-trip to apps/api. See DECISIONS
"Why shared HS256 secret between api and ragent".
"""

from __future__ import annotations

from typing import Final, Literal

from jose import JWTError, jwt
from pydantic import BaseModel

from promptforge_ragent.core.config import get_settings

JWT_ALGORITHM: Final = "HS256"


class InvalidTokenError(Exception):
    """Raised when an access token cannot be decoded or fails validation."""


class AccessTokenPayload(BaseModel):
    sub: str
    org: str
    role: str
    iat: int
    exp: int
    typ: Literal["access"] = "access"


def decode_access_token(token: str) -> AccessTokenPayload:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret.get_secret_value(), algorithms=[JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("typ") != "access":
        raise InvalidTokenError("invalid token type")
    return AccessTokenPayload.model_validate(payload)
