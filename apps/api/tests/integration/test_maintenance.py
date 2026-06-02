"""Integration test for the refresh-token reaper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.models import Org, RefreshToken, User
from promptforge_api.services.maintenance import reap_expired_refresh_tokens

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_reaper_deletes_only_tokens_past_retention(db_session: AsyncSession) -> None:
    user = User(email="reap@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    org = Org(name="Reap Org", slug="reap-org")
    db_session.add(org)
    await db_session.flush()

    now = datetime.now(UTC)

    def _token(hmac: str, expires_at: datetime) -> RefreshToken:
        return RefreshToken(
            user_id=user.id,
            org_id=org.id,
            chain_id=uuid4(),
            token_hmac=hmac,
            expires_at=expires_at,
        )

    db_session.add_all(
        [
            _token("long-expired", now - timedelta(days=100)),  # past 90d retention → reaped
            _token("recently-expired", now - timedelta(days=10)),  # within retention → kept
            _token("still-valid", now + timedelta(days=5)),  # not expired → kept
        ]
    )
    await db_session.flush()

    deleted = await reap_expired_refresh_tokens(db_session, retention_days=90)

    # Scope assertions to this test's own tokens — the shared container may hold
    # committed rows from other tests (db_session only rolls back its own writes).
    mine = {"long-expired", "recently-expired", "still-valid"}
    assert deleted >= 1
    surviving = set(
        (
            await db_session.execute(
                select(RefreshToken.token_hmac).where(RefreshToken.token_hmac.in_(mine))
            )
        )
        .scalars()
        .all()
    )
    assert surviving == {"recently-expired", "still-valid"}
