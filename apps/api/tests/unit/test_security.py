"""Unit tests for promptforge_api.core.security."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from freezegun import freeze_time
from jose import jwt

from promptforge_api.core.config import get_settings
from promptforge_api.core.security import (
    API_KEY_PUBLIC_PREFIX,
    JWT_ALGORITHM,
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_api_key,
    generate_refresh_token,
    hash_password,
    hmac_token,
    parse_api_key_prefix,
    verify_api_key,
    verify_password,
    verify_refresh_token,
)


@pytest.fixture(autouse=True)
def _cache_clear(base_env: None) -> None:
    get_settings.cache_clear()


# --- passwords -----------------------------------------------------------------------


def test_hash_password_verifies_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True


def test_hash_password_rejects_wrong_password() -> None:
    hashed = hash_password("right")
    assert verify_password("wrong", hashed) is False


def test_verify_password_rejects_invalid_hash_format() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


def test_hash_password_produces_distinct_hashes_for_same_input() -> None:
    first = hash_password("same")
    second = hash_password("same")
    assert first != second
    assert verify_password("same", first)
    assert verify_password("same", second)


# --- JWT access tokens ---------------------------------------------------------------


def test_create_and_decode_access_token_round_trip() -> None:
    user_id = uuid4()
    org_id = uuid4()
    token = create_access_token(user_id=user_id, org_id=org_id, role="owner")
    payload = decode_access_token(token)
    assert payload.sub == str(user_id)
    assert payload.org == str(org_id)
    assert payload.role == "owner"
    assert payload.typ == "access"


def test_decode_invalid_token_raises() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-jwt")


def test_decode_token_wrong_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    token = create_access_token(user_id=uuid4(), org_id=uuid4(), role="owner")
    monkeypatch.setenv("PF_JWT_SECRET", "z" * 48)
    get_settings.cache_clear()
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_rejects_non_access_typ() -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": str(uuid4()),
            "org": str(uuid4()),
            "role": "owner",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "typ": "refresh",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(forged)


def test_expired_access_token_raises() -> None:
    with freeze_time("2026-01-01 00:00:00"):
        token = create_access_token(user_id=uuid4(), org_id=uuid4(), role="owner")
    with freeze_time("2026-01-02 00:00:00"), pytest.raises(InvalidTokenError):
        decode_access_token(token)


# --- refresh tokens (HMAC) -----------------------------------------------------------


def test_generate_refresh_token_returns_distinct_pair() -> None:
    plain, hmac_hex = generate_refresh_token()
    assert plain != hmac_hex
    assert len(plain) >= 32
    assert len(hmac_hex) == 64  # sha256 hex


def test_hmac_token_is_deterministic_for_same_input() -> None:
    assert hmac_token("abc") == hmac_token("abc")


def test_hmac_token_changes_with_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    first = hmac_token("abc")
    monkeypatch.setenv("PF_JWT_SECRET", "z" * 48)
    get_settings.cache_clear()
    assert hmac_token("abc") != first


def test_verify_refresh_token_round_trip() -> None:
    plain, hmac_hex = generate_refresh_token()
    assert verify_refresh_token(plain, hmac_hex) is True
    assert verify_refresh_token("tampered", hmac_hex) is False


# --- API keys ------------------------------------------------------------------------


def test_generate_api_key_format_and_verify() -> None:
    plain, prefix, hashed = generate_api_key()
    assert plain.startswith(API_KEY_PUBLIC_PREFIX)
    assert f"_{prefix}_" in plain  # prefix is wrapped in underscores
    assert verify_api_key(plain, hashed) is True
    assert verify_api_key("pf_live_xxxxxxxx_tampered", hashed) is False


def test_parse_api_key_prefix_valid() -> None:
    plain, prefix, _ = generate_api_key()
    assert parse_api_key_prefix(plain) == prefix


def test_generated_prefix_round_trips_every_time() -> None:
    # Regression: the prefix used to be token_urlsafe, whose alphabet includes
    # '_'. With the old split('_') parser, ~12% of keys parsed to the wrong
    # prefix and failed lookup with a 401. 200 iterations makes that near-certain
    # to catch; all must round-trip exactly.
    for _ in range(200):
        plain, prefix, _hashed = generate_api_key()
        assert "_" not in prefix
        assert parse_api_key_prefix(plain) == prefix


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "not-a-key",
        "pf_live_short",
        "pf_live_short_secret",  # prefix too short
        "Bearer abc.def.ghi",
    ],
)
def test_parse_api_key_prefix_rejects_non_keys(candidate: str) -> None:
    assert parse_api_key_prefix(candidate) is None
