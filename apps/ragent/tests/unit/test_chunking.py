"""Unit: token-window chunking."""

import tiktoken

from promptforge_ragent.services.chunking import chunk_text


def test_empty_text_yields_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_is_one_chunk() -> None:
    chunks = chunk_text("hello world", target_tokens=512, overlap_tokens=64)
    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert chunks[0].text == "hello world"
    assert chunks[0].token_count > 0


def test_long_text_splits_into_overlapping_windows() -> None:
    enc = tiktoken.get_encoding("cl100k_base")
    text = " ".join(f"word{i}" for i in range(250))
    chunks = chunk_text(text, target_tokens=50, overlap_tokens=10)

    assert len(chunks) > 1
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(c.token_count <= 50 for c in chunks)

    # The chunks are exactly the sliding token windows: size 50, step 40 (= 50-10).
    tokens = enc.encode(text)
    assert chunks[0].text == enc.decode(tokens[0:50]).strip()
    assert chunks[1].text == enc.decode(tokens[40:90]).strip()


def test_invalid_overlap_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="overlap_tokens"):
        chunk_text("x", target_tokens=10, overlap_tokens=10)
