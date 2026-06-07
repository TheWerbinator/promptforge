"""Integration: the agent tools against real Postgres + pgvector (litellm mocked)."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.agent.tools import ToolContext, execute_tool
from promptforge_ragent.core.config import get_settings
from promptforge_ragent.models import Chunk, Corpus, Document, DocumentStatus, EmbeddingModel
from promptforge_ragent.services import retrieval

pytestmark = pytest.mark.integration

_NEAR = [1.0] + [0.0] * 1535


def _patch_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    # search_docs → rerank → get_settings(), so the minimal env must be present
    # (rerank stays disabled by default → passthrough, no torch).
    monkeypatch.setenv("PF_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()

    async def fake_embed(model: object, texts: list[str]) -> list[list[float]]:
        return [_NEAR]

    monkeypatch.setattr(retrieval, "embed_texts", fake_embed)


async def _seed(session: AsyncSession) -> tuple[Corpus, dict[str, Chunk]]:
    org_id = uuid4()
    await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
    corpus = Corpus(
        org_id=org_id, slug="docs", name="Docs", embedding_model=EmbeddingModel.OPENAI_3_SMALL
    )
    session.add(corpus)
    await session.flush()
    doc = Document(
        corpus_id=corpus.id,
        org_id=org_id,
        title="Handbook",
        status=DocumentStatus.READY,
        byte_size=1,
    )
    session.add(doc)
    await session.flush()
    chunks: dict[str, Chunk] = {}
    for i, content in enumerate(["quick brown fox", "the slow green turtle"]):
        c = Chunk(
            document_id=doc.id,
            corpus_id=corpus.id,
            org_id=org_id,
            ordinal=i,
            content=content,
            embedding_1536=_NEAR if i == 0 else [0.0, 1.0] + [0.0] * 1534,
        )
        session.add(c)
        chunks[content] = c
    await session.flush()
    return corpus, chunks


async def test_search_docs_returns_ranked_results(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embedding(monkeypatch)
    corpus, _ = await _seed(db_session)
    ctx = ToolContext(session=db_session, corpus=corpus)

    out = await execute_tool("search_docs", {"query": "quick fox", "top_k": 2}, ctx)
    assert "results" in out
    assert len(out["results"]) >= 1
    top = out["results"][0]
    assert top["document_title"] == "Handbook"
    assert "quick" in top["snippet"]
    assert "chunk_id" in top
    assert "score" in top


async def test_search_docs_requires_query(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embedding(monkeypatch)
    corpus, _ = await _seed(db_session)
    ctx = ToolContext(session=db_session, corpus=corpus)
    out = await execute_tool("search_docs", {"query": "   "}, ctx)
    assert "error" in out


async def test_fetch_passage_returns_full_content_and_scopes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embedding(monkeypatch)
    corpus, chunks = await _seed(db_session)
    ctx = ToolContext(session=db_session, corpus=corpus)
    target = chunks["quick brown fox"]

    out = await execute_tool("fetch_passage", {"chunk_id": str(target.id)}, ctx)
    assert out["content"] == "quick brown fox"
    assert out["document_title"] == "Handbook"

    # Bad id and out-of-corpus id both error.
    assert "error" in await execute_tool("fetch_passage", {"chunk_id": "nope"}, ctx)
    assert "error" in await execute_tool("fetch_passage", {"chunk_id": str(uuid4())}, ctx)


async def test_fetch_passage_rejects_other_corpus(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embedding(monkeypatch)
    corpus, _ = await _seed(db_session)
    _other_corpus, other_chunks = await _seed(db_session)
    ctx = ToolContext(session=db_session, corpus=corpus)

    foreign = other_chunks["quick brown fox"]
    out = await execute_tool("fetch_passage", {"chunk_id": str(foreign.id)}, ctx)
    assert "error" in out


async def test_cite_sources_projects_valid_ids_in_order(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embedding(monkeypatch)
    corpus, chunks = await _seed(db_session)
    _other, other_chunks = await _seed(db_session)
    ctx = ToolContext(session=db_session, corpus=corpus)

    a = chunks["quick brown fox"].id
    b = chunks["the slow green turtle"].id
    foreign = other_chunks["quick brown fox"].id

    out = await execute_tool("cite_sources", {"chunk_ids": [str(b), str(foreign), str(a)]}, ctx)
    cited = [c["chunk_id"] for c in out["citations"]]
    # Requested order preserved; the foreign (out-of-corpus) id dropped.
    assert cited == [str(b), str(a)]
    assert all(c["document_title"] == "Handbook" for c in out["citations"])


async def test_cite_sources_validates_input(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_embedding(monkeypatch)
    corpus, _ = await _seed(db_session)
    ctx = ToolContext(session=db_session, corpus=corpus)
    assert "error" in await execute_tool("cite_sources", {"chunk_ids": []}, ctx)
    assert "error" in await execute_tool("cite_sources", {"chunk_ids": ["bad"]}, ctx)
