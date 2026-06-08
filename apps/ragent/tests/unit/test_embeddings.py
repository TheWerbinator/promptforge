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


class _FakeBge:
    """Stands in for SentenceTransformer — no torch."""

    def __init__(self) -> None:
        self.last_inputs: list[str] | None = None
        self.last_normalize: bool | None = None

    def encode(self, inputs: list[str], normalize_embeddings: bool) -> list[list[float]]:
        self.last_inputs = list(inputs)
        self.last_normalize = normalize_embeddings
        return [[0.02] * 384 for _ in inputs]


def _patch_bge(monkeypatch: pytest.MonkeyPatch) -> _FakeBge:
    fake = _FakeBge()
    monkeypatch.setattr(embeddings, "_get_bge_model", lambda name: fake)
    return fake


async def test_bge_passages_have_no_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_bge(monkeypatch)
    out = await embed_texts(EmbeddingModel.BGE_SMALL_EN, ["alpha", "beta"])
    assert len(out) == 2
    assert all(len(v) == 384 for v in out)
    assert fake.last_inputs == ["alpha", "beta"]  # no query instruction on passages
    assert fake.last_normalize is True


async def test_bge_query_prepends_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_bge(monkeypatch)
    await embed_texts(EmbeddingModel.BGE_SMALL_EN, ["what is x"], is_query=True)
    assert fake.last_inputs is not None
    assert fake.last_inputs[0].startswith("Represent this sentence for searching")
    assert fake.last_inputs[0].endswith("what is x")


async def test_bge_dimension_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class WrongDim(_FakeBge):
        def encode(self, inputs: list[str], normalize_embeddings: bool) -> list[list[float]]:
            return [[0.0] * 1536 for _ in inputs]

    monkeypatch.setattr(embeddings, "_get_bge_model", lambda name: WrongDim())
    with pytest.raises(EmbeddingError, match="384-d"):
        await embed_texts(EmbeddingModel.BGE_SMALL_EN, ["a"])


async def test_openai_ignores_is_query(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_aembedding(**kwargs: object) -> SimpleNamespace:
        captured["input"] = kwargs["input"]
        texts = kwargs["input"]
        assert isinstance(texts, list)
        return _fake_response([[0.1] * 1536 for _ in texts])

    monkeypatch.setattr(embeddings.litellm, "aembedding", fake_aembedding)
    await embed_texts(EmbeddingModel.OPENAI_3_SMALL, ["q"], is_query=True)
    assert captured["input"] == ["q"]  # no instruction injected on the OpenAI path
