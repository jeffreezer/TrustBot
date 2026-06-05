"""No-op reranker (``RERANKER_PROVIDER=none``).

Keeps the incoming candidate order — useful to isolate the effect of the reranker,
or to run retrieval where the cross-encoder isn't available. Every candidate gets an
equal score, so ``rerank``'s stable sort preserves the fusion order exactly.
"""
from __future__ import annotations

from .rerank_base import RerankProvider


class PassthroughRerankProvider(RerankProvider):
    name = "passthrough"

    def score(self, query: str, documents: list[str]) -> list[float]:
        return [0.0 for _ in documents]
