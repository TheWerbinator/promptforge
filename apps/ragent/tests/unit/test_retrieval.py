"""Unit: RRF fusion + tokenizer (pure functions)."""

from uuid import uuid4

from promptforge_ragent.services.retrieval import _tokenize, reciprocal_rank_fusion


def test_tokenize_lowercases_and_splits() -> None:
    assert _tokenize("Quick, brown FOX!") == ["quick", "brown", "fox"]
    assert _tokenize("") == []


def test_rrf_empty() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_rrf_single_list_preserves_order() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    fused = reciprocal_rank_fusion([[a, b, c]], k=60)
    assert [item for item, _ in fused] == [a, b, c]
    assert fused[0][1] == 1 / 61  # top item: 1/(k+1)


def test_rrf_rewards_appearing_in_both_lists() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    # `a` is in both lists; `b` and `c` each in one.
    fused = reciprocal_rank_fusion([[a, b], [a, c]], k=60)
    ranked = [item for item, _ in fused]
    assert ranked[0] == a
    # a's score is the sum of two contributions; b and c each have one.
    score = dict(fused)
    assert score[a] > score[b]
    assert score[a] > score[c]


def test_rrf_lower_rank_still_counts() -> None:
    a, b = uuid4(), uuid4()
    # b is rank-1 in the second list, rank-2 in the first; a is rank-1 then absent.
    fused = dict(reciprocal_rank_fusion([[a, b], [b]], k=60))
    # b: 1/62 + 1/61 ; a: 1/61 — b edges ahead by appearing twice.
    assert fused[b] > fused[a]
