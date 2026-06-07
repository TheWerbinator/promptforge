"""Optional cross-encoder reranking of retrieved chunks.

A cross-encoder (bge-reranker-base) scores each (query, chunk) pair with full
attention — more accurate than the bi-encoder embeddings used for retrieval, but
it needs sentence-transformers/torch and a model load. So it's **off by default**
(`PF_RERANK_ENABLED=false`) and the dependency lives in the optional `rerank`
extra: with it disabled, `rerank` is a passthrough (the hybrid RRF order stands).
When enabled, the model is lazy-imported + cached and inference runs in a thread
so it doesn't block the event loop. Enabling it means installing the extra and
running on a machine sized for torch — documented, not shipped.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from promptforge_ragent.core.config import get_settings

if TYPE_CHECKING:
    from promptforge_ragent.services.retrieval import RetrievedChunk

_model: object | None = None


def _get_model(name: str) -> object:
    """Lazy-load + cache the CrossEncoder. Requires the optional `rerank` extra."""
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder

        _model = CrossEncoder(name)
    return _model


def _cross_encoder_scores(query: str, texts: list[str]) -> list[float]:
    model = _get_model(get_settings().rerank_model)
    scores = model.predict([(query, text) for text in texts])  # type: ignore[attr-defined]
    return [float(s) for s in scores]


async def rerank(
    query: str, chunks: list[RetrievedChunk], *, top_n: int | None = None
) -> list[RetrievedChunk]:
    """Reorder `chunks` by cross-encoder relevance when enabled; else passthrough.

    Returns chunks truncated to `top_n` (if given). When enabled, each returned
    chunk's `score` is replaced with its cross-encoder score.
    """
    settings = get_settings()
    if not settings.rerank_enabled or len(chunks) <= 1:
        return list(chunks[:top_n]) if top_n is not None else list(chunks)

    scores = await asyncio.to_thread(_cross_encoder_scores, query, [c.content for c in chunks])
    ranked = sorted(zip(chunks, scores, strict=True), key=lambda cs: cs[1], reverse=True)
    reordered = [replace(chunk, score=score) for chunk, score in ranked]
    return reordered[:top_n] if top_n is not None else reordered
