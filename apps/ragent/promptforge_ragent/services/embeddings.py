"""Embed texts, routing on the corpus's pinned embedding model.

The OpenAI path (text-embedding-3-small, 1536-d) goes through litellm — same
client and cost-tracking story as apps/api. The local bge-small path (384-d) is
a documented seam wired in Phase 12; raising here keeps the routing contract
honest rather than silently producing wrong-dimension vectors.
"""

from __future__ import annotations

import litellm

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.models import EmbeddingModel

_OPENAI_MODEL = "text-embedding-3-small"


class EmbeddingError(RuntimeError):
    """Raised when embedding fails or is misconfigured (terminal for ingest)."""


async def embed_texts(model: EmbeddingModel, texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per input text, in order."""
    if not texts:
        return []
    if model is EmbeddingModel.OPENAI_3_SMALL:
        return await _embed_openai(texts)
    if model is EmbeddingModel.BGE_SMALL_EN:
        # TODO(phase-12): local bge-small-en-v1.5 via sentence-transformers.
        raise EmbeddingError("local bge embedding backend lands in phase 12")
    raise EmbeddingError(f"unknown embedding model: {model!r}")


async def _embed_openai(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    try:
        response = await litellm.aembedding(model=_OPENAI_MODEL, input=texts, api_key=key)
    except Exception as exc:  # normalize any provider error into EmbeddingError
        raise EmbeddingError(f"openai embedding call failed: {exc}") from exc

    vectors = [item["embedding"] for item in response.data]
    expected = EmbeddingModel.OPENAI_3_SMALL.dim
    if any(len(v) != expected for v in vectors):
        raise EmbeddingError(f"expected {expected}-d vectors from {_OPENAI_MODEL}")
    return vectors
