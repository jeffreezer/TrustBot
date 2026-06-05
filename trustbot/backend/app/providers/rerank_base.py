"""Reranker provider interface.

A reranker is a second-pass model that re-scores hybrid-search candidates against
the query so the genuinely most relevant chunk ends up on top. Like the embedding
providers, every concrete reranker lives in this package (CLAUDE.md: "one
provider-abstraction module for all model/embedding/reranker access") — the
retrieval code depends only on the ``RerankProvider`` contract.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class RerankProvider(ABC):
    """Scores how well each candidate document answers a query (higher = better)."""

    name: str = "base"

    @abstractmethod
    def score(self, query: str, documents: list[str]) -> list[float]:
        """Return one relevance score per document, in input order."""

    def rerank(self, query: str, documents: list[str]) -> list[int]:
        """Return document indices sorted best-first.

        A stable sort keeps the incoming (fusion) order as the tie-breaker, so a
        passthrough/degenerate scorer never reshuffles already-good candidates.
        """
        if not documents:
            return []
        scores = self.score(query, documents)
        return sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)
