"""Split text into token-bounded, overlapping chunks for embedding.

Fixed-size sliding token windows: encode once with tiktoken's `cl100k_base`
(what text-embedding-3-small uses), then walk the token stream in steps of
`target_tokens - overlap_tokens`, decoding each window back to text. The overlap
keeps a fact that straddles a window boundary retrievable from both sides.

# considered paragraph-aware packing; chose fixed token windows for determinism
# and trivial testability. Semantic/recursive splitting (respecting headings and
# sentence boundaries) is the documented quality improvement if retrieval shows
# mid-sentence cuts hurting relevance.
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

_ENCODING = "cl100k_base"


@dataclass(frozen=True)
class TextChunk:
    ordinal: int
    text: str
    token_count: int


def chunk_text(
    text: str,
    *,
    target_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[TextChunk]:
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if not 0 <= overlap_tokens < target_tokens:
        raise ValueError("overlap_tokens must be in [0, target_tokens)")

    enc = tiktoken.get_encoding(_ENCODING)
    tokens = enc.encode(text)
    if not tokens:
        return []

    step = target_tokens - overlap_tokens
    chunks: list[TextChunk] = []
    ordinal = 0
    for start in range(0, len(tokens), step):
        window = tokens[start : start + target_tokens]
        body = enc.decode(window).strip()
        if body:
            chunks.append(TextChunk(ordinal=ordinal, text=body, token_count=len(window)))
            ordinal += 1
        if start + target_tokens >= len(tokens):
            break
    return chunks
