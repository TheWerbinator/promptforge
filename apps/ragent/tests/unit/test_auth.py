"""Unit: access-token decode + get_principal."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from promptforge_ragent.core.deps import get_principal
from promptforge_ragent.core.security import InvalidTokenError, decode_access_token

pytestmark = pytest.mark.usefixtures("base_env")

_SECRET = "a" * 48


def _token(**overrides: object) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "org": str(uuid4()),
        "role": "member",
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    payload.update(overrides)
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def test_decode_valid_token() -> None:
    org = str(uuid4())
    payload = decode_access_token(_token(org=org))
    assert payload.org == org
    assert payload.typ == "access"


def test_decode_rejects_bad_signature() -> None:
    token = jwt.encode({"sub": "x", "typ": "access"}, "wrong-secret" * 4, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_rejects_non_access_typ() -> None:
    with pytest.raises(InvalidTokenError, match="invalid token type"):
        decode_access_token(_token(typ="refresh"))


async def test_get_principal_happy() -> None:
    user_id, org_id = uuid4(), uuid4()
    creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=_token(sub=str(user_id), org=str(org_id))
    )
    principal = await get_principal(creds)
    assert principal.user_id == user_id
    assert principal.org_id == org_id
    assert principal.role == "member"


async def test_get_principal_missing_credentials() -> None:
    with pytest.raises(HTTPException) as exc:
        await get_principal(None)
    assert exc.value.status_code == 401


async def test_get_principal_invalid_token() -> None:
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage.token.here")
    with pytest.raises(HTTPException) as exc:
        await get_principal(creds)
    assert exc.value.status_code == 401
