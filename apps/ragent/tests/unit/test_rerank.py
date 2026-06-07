"""Unit: rerank passthrough (disabled) + reordering (enabled, scorer mocked).

The cross-encoder itself (torch) is never loaded here — the enabled path mocks
`_cross_encoder_scores`, so the reorder logic is tested without the heavy extra.
"""

from uuid import uuid4

import pytest

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.services import rerank as rerank_module
from promptforge_ragent.services.rerank import rerank
from promptforge_ragent.services.retrieval import RetrievedChunk


def _chunk(content: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        corpus_id=uuid4(),
        ordinal=0,
        content=content,
        score=score,
    )


def _enable_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PF_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    monkeypatch.setenv("PF_RERANK_ENABLED", "true")
    get_settings.cache_clear()


async def test_disabled_is_passthrough(base_env: None) -> None:
    chunks = [_chunk("a", 0.3), _chunk("b", 0.2), _chunk("c", 0.1)]
    out = await rerank("q", chunks)
    assert out == chunks  # order + objects unchanged


async def test_disabled_still_truncates_to_top_n(base_env: None) -> None:
    chunks = [_chunk("a", 0.3), _chunk("b", 0.2), _chunk("c", 0.1)]
    out = await rerank("q", chunks, top_n=2)
    assert out == chunks[:2]


async def test_enabled_reorders_by_cross_encoder_score(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_rerank(monkeypatch)
    # Hybrid order is a, b, c; the cross-encoder disagrees: c is most relevant.
    chunks = [_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)]
    score_map = {"a": 0.1, "b": 0.5, "c": 0.99}

    def fake_scores(query: str, texts: list[str]) -> list[float]:
        return [score_map[t] for t in texts]

    monkeypatch.setattr(rerank_module, "_cross_encoder_scores", fake_scores)

    out = await rerank("q", chunks, top_n=2)
    assert [c.content for c in out] == ["c", "b"]
    assert out[0].score == 0.99  # score replaced with the cross-encoder score


async def test_enabled_single_chunk_is_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_rerank(monkeypatch)

    # <=1 chunk: nothing to reorder, scorer must not be called.
    def boom(query: str, texts: list[str]) -> list[float]:
        raise AssertionError("scorer should not run for a single chunk")

    monkeypatch.setattr(rerank_module, "_cross_encoder_scores", boom)
    chunks = [_chunk("only", 0.4)]
    assert await rerank("q", chunks) == chunks
