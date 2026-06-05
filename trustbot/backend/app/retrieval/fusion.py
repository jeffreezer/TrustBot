"""Reciprocal Rank Fusion — combine ranked lists without comparing score scales.

Vector cosine distance and full-text ``ts_rank`` are on different, incomparable
scales, so we fuse by *rank* rather than raw score. Each item scores
``sum(1 / (k + rank))`` over the lists it appears in (rank 1-based); items in both
lists accumulate from both. The constant ``k`` (canonically 60) damps the pull of
the very top ranks so no single retriever dominates.

Pure and DB-free, so it's unit-tested directly.
"""
from __future__ import annotations

from collections.abc import Hashable, Sequence
from typing import TypeVar

K = TypeVar("K", bound=Hashable)

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[K]], *, k: int = DEFAULT_RRF_K
) -> list[tuple[K, float]]:
    """Fuse ranked lists into one (item, score) list sorted best-first.

    Ties break by first appearance across the input lists, so the result is
    deterministic regardless of dict iteration order.
    """
    scores: dict[K, float] = {}
    first_seen: dict[K, int] = {}
    order = 0
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
            if item not in first_seen:
                first_seen[item] = order
                order += 1
    return sorted(scores.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))
