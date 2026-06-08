"""E2E: corpora REST + document upload (→ ingest job enqueued)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from promptforge_ragent.core.config import get_settings

pytestmark = pytest.mark.e2e

_SECRET = "a" * 48


def _token(user_id: UUID, org_id: UUID, role: str = "member") -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(org_id),
        "role": role,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, _SECRET, algorithm="HS256")


async def _seed_principal(factory: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    async with factory() as session:
        org_id, user_id = uuid4(), uuid4()
        await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
        await session.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": user_id})
        await session.commit()
    return org_id, user_id


def _auth(user_id: UUID, org_id: UUID, role: str = "member") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id, org_id, role)}"}


async def test_create_list_corpus(
    app_client: AsyncClient, committed_db: async_sessionmaker[AsyncSession]
) -> None:
    org_id, user_id = await _seed_principal(committed_db)
    h = _auth(user_id, org_id)

    resp = await app_client.post(
        "/api/v1/corpora", json={"slug": "my-docs", "name": "My Docs"}, headers=h
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "my-docs"
    assert resp.json()["document_count"] == 0

    listed = await app_client.get("/api/v1/corpora", headers=h)
    assert listed.status_code == 200
    assert [c["slug"] for c in listed.json()] == ["my-docs"]


async def test_create_corpus_demo_forbidden(
    app_client: AsyncClient, committed_db: async_sessionmaker[AsyncSession]
) -> None:
    org_id, user_id = await _seed_principal(committed_db)
    resp = await app_client.post(
        "/api/v1/corpora",
        json={"slug": "x", "name": "X"},
        headers=_auth(user_id, org_id, role="demo"),
    )
    assert resp.status_code == 403


async def test_duplicate_slug_conflicts(
    app_client: AsyncClient, committed_db: async_sessionmaker[AsyncSession]
) -> None:
    org_id, user_id = await _seed_principal(committed_db)
    h = _auth(user_id, org_id)
    body = {"slug": "dup", "name": "Dup"}
    assert (await app_client.post("/api/v1/corpora", json=body, headers=h)).status_code == 201
    assert (await app_client.post("/api/v1/corpora", json=body, headers=h)).status_code == 409


async def test_upload_creates_document_and_enqueues_ingest(
    app_client: AsyncClient, committed_db: async_sessionmaker[AsyncSession]
) -> None:
    org_id, user_id = await _seed_principal(committed_db)
    h = _auth(user_id, org_id)
    corpus = (
        await app_client.post("/api/v1/corpora", json={"slug": "docs", "name": "Docs"}, headers=h)
    ).json()

    resp = await app_client.post(
        f"/api/v1/corpora/{corpus['id']}/documents",
        files={"file": ("readme.md", b"# Title\n\nHello world.", "text/markdown")},
        headers=h,
    )
    assert resp.status_code == 201
    doc = resp.json()
    assert doc["status"] == "pending"
    assert doc["content_type"] == "markdown"
    assert doc["byte_size"] > 0

    # Document persisted + an ingest job enqueued for it.
    listed = await app_client.get(f"/api/v1/corpora/{corpus['id']}/documents", headers=h)
    assert [d["id"] for d in listed.json()] == [doc["id"]]

    async with committed_db() as session:
        job = (
            (
                await session.execute(
                    text("SELECT kind, payload FROM jobs WHERE payload->>'document_id' = :d"),
                    {"d": doc["id"]},
                )
            )
            .mappings()
            .one()
        )
    assert job["kind"] == "ingest_document"


async def test_upload_rejects_unknown_type(
    app_client: AsyncClient, committed_db: async_sessionmaker[AsyncSession]
) -> None:
    org_id, user_id = await _seed_principal(committed_db)
    h = _auth(user_id, org_id)
    corpus = (
        await app_client.post("/api/v1/corpora", json={"slug": "docs", "name": "Docs"}, headers=h)
    ).json()
    resp = await app_client.post(
        f"/api/v1/corpora/{corpus['id']}/documents",
        files={"file": ("data.xlsx", b"binary", "application/octet-stream")},
        headers=h,
    )
    assert resp.status_code == 415


async def test_upload_enforces_file_size_cap(
    app_client: AsyncClient,
    committed_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, user_id = await _seed_principal(committed_db)
    h = _auth(user_id, org_id)
    corpus = (
        await app_client.post("/api/v1/corpora", json={"slug": "docs", "name": "Docs"}, headers=h)
    ).json()

    monkeypatch.setenv("PF_MAX_FILE_BYTES", "8")
    get_settings.cache_clear()
    resp = await app_client.post(
        f"/api/v1/corpora/{corpus['id']}/documents",
        files={"file": ("big.txt", b"way more than eight bytes", "text/plain")},
        headers=h,
    )
    assert resp.status_code == 413


async def test_upload_cross_org_corpus_not_found(
    app_client: AsyncClient, committed_db: async_sessionmaker[AsyncSession]
) -> None:
    org_a, user_a = await _seed_principal(committed_db)
    org_b, user_b = await _seed_principal(committed_db)
    corpus = (
        await app_client.post(
            "/api/v1/corpora",
            json={"slug": "docs", "name": "Docs"},
            headers=_auth(user_a, org_a),
        )
    ).json()

    resp = await app_client.post(
        f"/api/v1/corpora/{corpus['id']}/documents",
        files={"file": ("readme.md", b"# hi", "text/markdown")},
        headers=_auth(user_b, org_b),
    )
    assert resp.status_code == 404
