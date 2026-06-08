"""Integration: corpora seed (real DB, embeddings mocked)."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.models import Chunk, Corpus, Document
from promptforge_ragent.seed import seed_corpora
from promptforge_ragent.seed_data import SEED_CORPORA
from promptforge_ragent.services import ingest as ingest_module

pytestmark = pytest.mark.integration

_TOTAL_DOCS = sum(len(c.documents) for c in SEED_CORPORA)


def _patch_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed(model: object, texts: list[str]) -> list[list[float]]:
        return [[0.05] * 1536 for _ in texts]

    monkeypatch.setattr(ingest_module, "embed_texts", fake_embed)


async def _seed_principal(session: AsyncSession) -> tuple[object, object]:
    org_id, user_id = uuid4(), uuid4()
    await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
    await session.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": user_id})
    return org_id, user_id


async def test_seed_creates_and_ingests_corpora(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embed(monkeypatch)
    org_id, user_id = await _seed_principal(db_session)

    counts = await seed_corpora(db_session, org_id=org_id, created_by=user_id)
    assert counts["corpora"] == len(SEED_CORPORA)
    assert counts["documents"] == _TOTAL_DOCS
    assert counts["ingested"] == _TOTAL_DOCS

    corpora = (await db_session.execute(select(func.count()).select_from(Corpus))).scalar_one()
    assert corpora == len(SEED_CORPORA)
    chunks = (await db_session.execute(select(func.count()).select_from(Chunk))).scalar_one()
    assert chunks >= _TOTAL_DOCS  # at least one chunk per document
    # Every document ingested to READY with a 1536-d vector.
    docs = (await db_session.execute(select(Document))).scalars().all()
    assert all(d.status.value == "ready" for d in docs)


async def test_seed_is_idempotent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embed(monkeypatch)
    org_id, user_id = await _seed_principal(db_session)

    first = await seed_corpora(db_session, org_id=org_id, created_by=user_id)
    chunks_after_first = (
        await db_session.execute(select(func.count()).select_from(Chunk))
    ).scalar_one()

    second = await seed_corpora(db_session, org_id=org_id, created_by=user_id)
    chunks_after_second = (
        await db_session.execute(select(func.count()).select_from(Chunk))
    ).scalar_one()

    assert first["ingested"] == _TOTAL_DOCS
    assert second["ingested"] == 0  # nothing re-ingested
    assert second["corpora"] == len(SEED_CORPORA)  # get-or-create, no duplicates
    assert chunks_after_first == chunks_after_second
