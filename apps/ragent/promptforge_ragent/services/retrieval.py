"""Hybrid retrieval: dense (pgvector) + sparse (BM25) fused with RRF.

Dense alone underperforms on lexical queries — exact names, error strings, code
identifiers — so a sparse BM25 pass covers that gap, and the two ranked lists are
combined with Reciprocal Rank Fusion. RRF needs only the *ranks*, not the scores,
so there's nothing to calibrate between cosine distance and BM25 magnitude
(Cormack et al.); this is the production-shape hybrid pattern.

BM25 runs in-process (rank-bm25) over the corpus's chunk texts. At demo scale the
index is rebuilt per query; caching it per corpus with ingest-invalidation is the
documented optimization once corpora grow.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.models import Chunk, Corpus
from promptforge_ragent.services.embeddings import embed_texts

_WORD = re.compile(r"\w+")
RRF_K = 60


def _tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    corpus_id: UUID
    ordinal: int
    content: str
    score: float  # fused RRF score


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[UUID]], *, k: int = RRF_K
) -> list[tuple[UUID, float]]:
    """Fuse ranked id lists into one, scored by sum(1 / (k + rank)).

    `rank` is 1-based: the top item of each list contributes 1/(k+1). An id that
    appears high in multiple lists accumulates the most. Returns (id, score)
    sorted by score descending.
    """
    scores: dict[UUID, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


async def _dense_ranking(
    session: AsyncSession, corpus: Corpus, query_vector: list[float], *, limit: int
) -> list[UUID]:
    column = Chunk.embedding_1536 if corpus.embedding_model.dim == 1536 else Chunk.embedding_384
    rows = (
        (
            await session.execute(
                select(Chunk.id)
                .where(
                    Chunk.corpus_id == corpus.id,
                    Chunk.org_id == corpus.org_id,
                    column.isnot(None),
                )
                .order_by(column.cosine_distance(query_vector))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _sparse_ranking(
    session: AsyncSession, corpus: Corpus, query: str, *, limit: int
) -> list[UUID]:
    rows = (
        await session.execute(
            select(Chunk.id, Chunk.content).where(
                Chunk.corpus_id == corpus.id, Chunk.org_id == corpus.org_id
            )
        )
    ).all()
    if not rows:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    ids = [r[0] for r in rows]
    bm25 = BM25Okapi([_tokenize(r[1]) for r in rows])
    scores = bm25.get_scores(query_tokens)
    ranked = sorted(zip(ids, scores, strict=True), key=lambda kv: kv[1], reverse=True)
    # Keep only positive-scoring (actually lexically-matching) chunks.
    return [chunk_id for chunk_id, score in ranked[:limit] if score > 0]


async def hybrid_search(
    session: AsyncSession,
    corpus: Corpus,
    query: str,
    *,
    top_n: int = 10,
    k_dense: int = 20,
    k_sparse: int = 20,
    rrf_k: int = RRF_K,
) -> list[RetrievedChunk]:
    """Return the top_n chunks for `query` in `corpus`, dense+sparse fused via RRF."""
    query = query.strip()
    if not query:
        return []

    query_vector = (await embed_texts(corpus.embedding_model, [query], is_query=True))[0]
    dense = await _dense_ranking(session, corpus, query_vector, limit=k_dense)
    sparse = await _sparse_ranking(session, corpus, query, limit=k_sparse)

    fused = reciprocal_rank_fusion([dense, sparse], k=rrf_k)[:top_n]
    if not fused:
        return []

    top_ids = [chunk_id for chunk_id, _ in fused]
    chunks = (await session.execute(select(Chunk).where(Chunk.id.in_(top_ids)))).scalars().all()
    by_id = {c.id: c for c in chunks}
    score_by_id = dict(fused)

    return [
        RetrievedChunk(
            chunk_id=c.id,
            document_id=c.document_id,
            corpus_id=c.corpus_id,
            ordinal=c.ordinal,
            content=c.content,
            score=score_by_id[c.id],
        )
        for cid in top_ids
        if (c := by_id.get(cid)) is not None
    ]
