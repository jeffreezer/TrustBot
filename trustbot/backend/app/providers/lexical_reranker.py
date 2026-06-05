"""Deterministic, dependency-free reranker for tests / offline CI.

Scores by lexical (token-overlap) similarity between query and document. Unlike a
pure hash, this produces *meaningful* ordering — the chunk that shares the most query
terms ranks highest — so retrieval ordering can be asserted in unit tests without
downloading the cross-encoder. Selected via ``RERANKER_PROVIDER=hash``.
"""
from __future__ import annotations

import re

from .rerank_base import RerankProvider

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


class LexicalRerankProvider(RerankProvider):
    name = "lexical"

    def score(self, query: str, documents: list[str]) -> list[float]:
        q = _tokens(query)
        if not q:
            return [0.0 for _ in documents]
        scores = []
        for doc in documents:
            d = _tokens(doc)
            overlap = len(q & d)
            scores.append(overlap / len(q))  # fraction of query terms present
        return scores
