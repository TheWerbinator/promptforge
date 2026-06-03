"""Password hashing, JWT issue/decode, opaque refresh tokens, API keys.

- Passwords: argon2id (OWASP 2024 recommendation).
- Access tokens: HS256 JWT signed with `Settings.jwt_secret`.
- Refresh tokens: random opaque strings; we store an HMAC-SHA256 (not argon2) so
  lookups are deterministic and fast. The token itself is high-entropy random, so
  password-grade hashing is unnecessary.
- API keys: format `pf_live_<prefix>_<secret>`. Prefix stored cleartext for O(1)
  lookup; full key hashed via argon2 (verify is rare and the hash protects against
  DB-leak replay).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jose import JWTError, jwt
from pydantic import BaseModel

from promptforge_api.core.config import get_settings

_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

JWT_ALGORITHM: Final = "HS256"

API_KEY_PUBLIC_PREFIX: Final = "pf_live_"
API_KEY_RANDOM_PREFIX_LEN: Final = 8  # chars
API_KEY_SECRET_BYTES: Final = 32


class InvalidTokenError(Exception):
    """Raised when an access token cannot be decoded or fails validation."""


class AccessTokenPayload(BaseModel):
    sub: str
    org: str
    role: str
    iat: int
    exp: int
    typ: Literal["access"] = "access"


def hash_password(plain: str) -> str:
    return _password_hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _password_hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(
    *,
    user_id: UUID,
    org_id: UUID,
    role: str,
    ttl_minutes: int | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    minutes = ttl_minutes if ttl_minutes is not None else settings.access_token_ttl_minutes
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> AccessTokenPayload:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("typ") != "access":
        raise InvalidTokenError("invalid token type")
    return AccessTokenPayload.model_validate(payload)


def generate_refresh_token() -> tuple[str, str]:
    """Return (plain_token, hmac_hex). Plain goes in the cookie, hmac in the DB."""
    plain = secrets.token_urlsafe(48)
    return plain, hmac_token(plain)


def generate_share_token() -> tuple[str, str]:
    """Return (plain_token, hmac_hex). Plain goes in the share URL, hmac in the DB."""
    plain = secrets.token_urlsafe(32)
    return plain, hmac_token(plain)


def hmac_token(plain: str) -> str:
    secret = get_settings().jwt_secret.get_secret_value().encode()
    return hmac.new(secret, plain.encode(), hashlib.sha256).hexdigest()


def verify_refresh_token(plain: str, stored_hmac: str) -> bool:
    return hmac.compare_digest(hmac_token(plain), stored_hmac)


# considered storing the prefix separately from the secret instead of embedding
# it; chose embedded so the full key the user sees encodes its own lookup hint.
def generate_api_key() -> tuple[str, str, str]:
    """Return (plain_key, prefix, argon2_hash)."""
    secret = secrets.token_urlsafe(API_KEY_SECRET_BYTES)
    # Hex prefix (not token_urlsafe): urlsafe's alphabet includes '_', which
    # collides with the '_' separator and used to break prefix parsing ~12% of
    # the time. Hex is unambiguous.
    prefix = secrets.token_hex((API_KEY_RANDOM_PREFIX_LEN + 1) // 2)[:API_KEY_RANDOM_PREFIX_LEN]
    plain = f"{API_KEY_PUBLIC_PREFIX}{prefix}_{secret}"
    return plain, prefix, _password_hasher.hash(plain)


def verify_api_key(plain: str, hashed: str) -> bool:
    try:
        return _password_hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def parse_api_key_prefix(plain: str) -> str | None:
    """Return the prefix if `plain` matches the API-key format, else None."""
    if not plain.startswith(API_KEY_PUBLIC_PREFIX):
        return None
    rest = plain[len(API_KEY_PUBLIC_PREFIX) :]
    # Parse by fixed length, not split('_'): the prefix is exactly
    # API_KEY_RANDOM_PREFIX_LEN chars, then the '_' separator, then the secret.
    # Splitting on '_' breaks if the prefix or secret contains one.
    if len(rest) <= API_KEY_RANDOM_PREFIX_LEN or rest[API_KEY_RANDOM_PREFIX_LEN] != "_":
        return None
    return rest[:API_KEY_RANDOM_PREFIX_LEN]
