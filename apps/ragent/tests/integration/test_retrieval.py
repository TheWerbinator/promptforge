"""Integration: hybrid_search against real Postgres + pgvector.

The point of hybrid retrieval is that a lexically-relevant chunk still surfaces
even when it's semantically far from the query embedding. These tests pin exactly
that: a dense-far but keyword-matching chunk is lifted above a dense-equal chunk
that has no keyword overlap.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.models import Chunk, Corpus, Document, DocumentStatus, EmbeddingModel
from promptforge_ragent.services import retrieval
from promptforge_ragent.services.retrieval import hybrid_search

pytestmark = pytest.mark.integration

# Three orthogonal unit vectors in 1536-d space.
_NEAR = [1.0] + [0.0] * 1535  # query points here
_FAR_B = [0.0] * 1535 + [1.0]
_FAR_C = [0.0, 1.0] + [0.0] * 1534


def _patch_query_embedding(monkeypatch: pytest.MonkeyPatch, vector: list[float]) -> None:
    async def fake_embed(model: object, texts: list[str], **kwargs: object) -> list[list[float]]:
        return [vector]

    monkeypatch.setattr(retrieval, "embed_texts", fake_embed)


async def _seed(session: AsyncSession) -> tuple[Corpus, dict[str, Chunk]]:
    org_id = uuid4()
    from sqlalchemy import text

    await session.execute(text("INSERT INTO orgs (id) VALUES (:id)"), {"id": org_id})
    corpus = Corpus(
        org_id=org_id, slug="docs", name="Docs", embedding_model=EmbeddingModel.OPENAI_3_SMALL
    )
    session.add(corpus)
    await session.flush()
    doc = Document(
        corpus_id=corpus.id, org_id=org_id, title="d", status=DocumentStatus.READY, byte_size=1
    )
    session.add(doc)
    await session.flush()

    specs = {
        # near in embedding AND keyword match
        "A": ("the quick brown fox", _NEAR),
        # far in embedding, no keyword overlap
        "B": ("lorem ipsum dolor sit amet", _FAR_B),
        # far in embedding BUT keyword match — only BM25 can surface this
        "C": ("quick fox jumps high", _FAR_C),
    }
    chunks: dict[str, Chunk] = {}
    for i, (label, (content, emb)) in enumerate(specs.items()):
        c = Chunk(
            document_id=doc.id,
            corpus_id=corpus.id,
            org_id=org_id,
            ordinal=i,
            content=content,
            embedding_1536=emb,
        )
        session.add(c)
        chunks[label] = c
    await session.flush()
    return corpus, chunks


async def test_hybrid_lifts_lexical_match_above_dense_equal(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_query_embedding(monkeypatch, _NEAR)
    corpus, chunks = await _seed(db_session)

    results = await hybrid_search(db_session, corpus, "quick fox", top_n=10)
    ids = [r.chunk_id for r in results]

    # A is best (near embedding + keyword match).
    assert ids[0] == chunks["A"].id
    # C (dense-far, keyword match) outranks B (dense-equal, no keywords) thanks to BM25.
    assert ids.index(chunks["C"].id) < ids.index(chunks["B"].id)


async def test_empty_query_returns_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_query_embedding(monkeypatch, _NEAR)
    corpus, _ = await _seed(db_session)
    assert await hybrid_search(db_session, corpus, "   ") == []


async def test_scoped_to_corpus(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_query_embedding(monkeypatch, _NEAR)
    corpus, chunks = await _seed(db_session)

    # A second corpus in a different org with a keyword-matching chunk.
    _other, other_chunks = await _seed(db_session)

    results = await hybrid_search(db_session, corpus, "quick fox", top_n=10)
    returned = {r.chunk_id for r in results}
    assert returned <= {c.id for c in chunks.values()}
    assert not (returned & {c.id for c in other_chunks.values()})
