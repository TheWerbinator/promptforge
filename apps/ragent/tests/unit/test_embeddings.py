"""Unit: embedding routing (litellm mocked)."""

from types import SimpleNamespace

import pytest

from promptforge_ragent.models import EmbeddingModel
from promptforge_ragent.services import embeddings
from promptforge_ragent.services.embeddings import EmbeddingError, embed_texts

pytestmark = pytest.mark.usefixtures("base_env")


def _fake_response(vectors: list[list[float]]) -> SimpleNamespace:
    return SimpleNamespace(data=[{"embedding": v} for v in vectors])


async def test_empty_input_skips_call() -> None:
    assert await embed_texts(EmbeddingModel.OPENAI_3_SMALL, []) == []


async def test_openai_path_returns_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_aembedding(**kwargs: object) -> SimpleNamespace:
        texts = kwargs["input"]
        assert isinstance(texts, list)
        captured["model"] = kwargs["model"]
        captured["n"] = len(texts)
        return _fake_response([[0.1] * 1536 for _ in texts])

    monkeypatch.setattr(embeddings.litellm, "aembedding", fake_aembedding)
    out = await embed_texts(EmbeddingModel.OPENAI_3_SMALL, ["a", "b"])
    assert len(out) == 2
    assert all(len(v) == 1536 for v in out)
    assert captured == {"model": "text-embedding-3-small", "n": 2}


async def test_dimension_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_aembedding(**kwargs: object) -> SimpleNamespace:
        return _fake_response([[0.1] * 384])

    monkeypatch.setattr(embeddings.litellm, "aembedding", fake_aembedding)
    with pytest.raises(EmbeddingError, match="1536-d"):
        await embed_texts(EmbeddingModel.OPENAI_3_SMALL, ["a"])


async def test_provider_error_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_aembedding(**kwargs: object) -> SimpleNamespace:
        raise RuntimeError("boom")

    monkeypatch.setattr(embeddings.litellm, "aembedding", fake_aembedding)
    with pytest.raises(EmbeddingError, match="call failed"):
        await embed_texts(EmbeddingModel.OPENAI_3_SMALL, ["a"])


async def test_bge_path_is_phase12_seam() -> None:
    with pytest.raises(EmbeddingError, match="phase 12"):
        await embed_texts(EmbeddingModel.BGE_SMALL_EN, ["a"])
