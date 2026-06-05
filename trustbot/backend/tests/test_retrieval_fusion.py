"""Reciprocal Rank Fusion — pure, DB-free tests of the hybrid-merge logic."""
from app.retrieval.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion


def test_item_in_both_lists_outranks_item_in_one():
    # "b" is mid-rank in both lists; "a" is only top of the first.
    vector = ["a", "b", "c"]
    keyword = ["d", "b", "e"]
    fused = reciprocal_rank_fusion([vector, keyword])
    order = [item for item, _ in fused]
    assert order[0] == "b"  # appearing in both lists wins


def test_score_matches_rrf_formula():
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["b"]], k=60))
    # "a": rank 1 in list one only -> 1/61
    # "b": rank 2 in list one + rank 1 in list two -> 1/62 + 1/61
    assert fused["a"] == 1 / 61
    assert fused["b"] == 1 / 62 + 1 / 61


def test_single_list_preserves_order():
    fused = reciprocal_rank_fusion([["x", "y", "z"]])
    assert [item for item, _ in fused] == ["x", "y", "z"]


def test_ties_break_by_first_appearance():
    # Two disjoint lists, each item rank 0 -> identical scores; order is stable.
    fused = reciprocal_rank_fusion([["a"], ["b"]])
    assert [item for item, _ in fused] == ["a", "b"]


def test_empty_input_returns_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_k_constant_damps_top_ranks():
    # Larger k flattens the gap between rank 1 and rank 2 contributions.
    small_k = dict(reciprocal_rank_fusion([["a", "b"]], k=1))
    large_k = dict(reciprocal_rank_fusion([["a", "b"]], k=1000))
    assert (small_k["a"] - small_k["b"]) > (large_k["a"] - large_k["b"])
    assert DEFAULT_RRF_K == 60
