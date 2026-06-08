"""Embed texts, routing on the corpus's pinned embedding model.

The OpenAI path (text-embedding-3-small, 1536-d) goes through litellm — same
client and cost-tracking story as apps/api. The local bge-small path (384-d) runs
sentence-transformers locally: no API cost, but it pulls torch, so it lives in the
optional `local-embeddings` extra and is loaded only when a corpus actually uses
it (seeded corpora are OpenAI, so the default never touches it). bge is a
*query-instruction* model — queries are prefixed for retrieval, passages aren't —
so `embed_texts` takes an `is_query` flag (the OpenAI path ignores it).
"""

from __future__ import annotations

import asyncio
from typing import Any

import litellm
from litellm.exceptions import APIConnectionError, APIError, RateLimitError, Timeout

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.models import EmbeddingModel

_OPENAI_MODEL = "text-embedding-3-small"
# bge-small-en-v1.5 retrieval instruction — prepended to queries only (BAAI docs).
_BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

# Transient provider failures worth a retry — same set apps/api retries on.
# Anything else (auth, invalid request, content policy) is terminal.
_RETRYABLE: tuple[type[BaseException], ...] = (
    APIConnectionError,
    Timeout,
    RateLimitError,
    APIError,
)


class EmbeddingError(RuntimeError):
    """Raised when embedding fails or is misconfigured (terminal for ingest)."""


class RetriableEmbeddingError(EmbeddingError):
    """A transient provider failure — the ingest worker should requeue, not fail."""


async def embed_texts(
    model: EmbeddingModel, texts: list[str], *, is_query: bool = False
) -> list[list[float]]:
    """Return one embedding vector per input text, in order.

    `is_query` only affects the bge path (prepends the retrieval instruction);
    pass it when embedding a search query rather than a passage.
    """
    if not texts:
        return []
    if model is EmbeddingModel.OPENAI_3_SMALL:
        return await _embed_openai(texts)
    if model is EmbeddingModel.BGE_SMALL_EN:
        return await _embed_bge(texts, is_query=is_query)
    raise EmbeddingError(f"unknown embedding model: {model!r}")


async def _embed_openai(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    try:
        response = await litellm.aembedding(model=_OPENAI_MODEL, input=texts, api_key=key)
    except _RETRYABLE as exc:  # transient → let the worker requeue with backoff
        raise RetriableEmbeddingError(f"transient embedding failure: {exc}") from exc
    except Exception as exc:  # terminal (auth, bad request, etc.)
        raise EmbeddingError(f"openai embedding call failed: {exc}") from exc

    vectors = [item["embedding"] for item in response.data]
    expected = EmbeddingModel.OPENAI_3_SMALL.dim
    if any(len(v) != expected for v in vectors):
        raise EmbeddingError(f"expected {expected}-d vectors from {_OPENAI_MODEL}")
    return vectors


_bge_model: Any | None = None


def _get_bge_model(name: str) -> Any:
    """Lazy-load + cache the SentenceTransformer. Requires the `local-embeddings` extra."""
    global _bge_model
    if _bge_model is None:
        from sentence_transformers import SentenceTransformer

        _bge_model = SentenceTransformer(name)
    return _bge_model


def _encode_bge(texts: list[str], is_query: bool) -> list[list[float]]:
    model = _get_bge_model(get_settings().embedding_bge_model)
    inputs = [_BGE_QUERY_INSTRUCTION + t for t in texts] if is_query else texts
    # normalize_embeddings=True so cosine distance is meaningful (BAAI guidance).
    vectors = model.encode(inputs, normalize_embeddings=True)
    return [[float(x) for x in vector] for vector in vectors]


async def _embed_bge(texts: list[str], *, is_query: bool) -> list[list[float]]:
    # CPU-bound + synchronous — run off the event loop.
    vectors = await asyncio.to_thread(_encode_bge, texts, is_query)
    expected = EmbeddingModel.BGE_SMALL_EN.dim
    if any(len(v) != expected for v in vectors):
        raise EmbeddingError(f"expected {expected}-d vectors from the bge model")
    return vectors
