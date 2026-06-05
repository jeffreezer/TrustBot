"""Embedding provider interface.

This package is the *single* place vendor/model-specific code lives (CLAUDE.md:
"one provider-abstraction module for all model/embedding/reranker access — never
import a vendor SDK elsewhere"). The rest of the app depends only on the
``EmbeddingProvider`` contract and never imports sentence-transformers, torch, or
an HTTP client directly.

Every provider must return fixed-width vectors matching the ``knowledge_chunks``
column (``EMBEDDING_DIM``); ``_validate`` enforces this so a misconfigured model
fails loudly rather than corrupting the table.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..db.models import EMBEDDING_DIM


class ProviderError(Exception):
    pass


class EmbeddingProvider(ABC):
    """Maps text to dense, fixed-width, L2-normalized vectors."""

    name: str = "base"

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIM

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents. Order of inputs is preserved."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query. BGE-M3 is symmetric, so this defaults to the
        document path; override if a provider needs a query-specific prefix."""
        return self.embed_documents([text])[0]

    def _validate(self, vectors: list[list[float]]) -> list[list[float]]:
        for vec in vectors:
            if len(vec) != self.dimension:
                raise ProviderError(
                    f"{self.name} returned dimension {len(vec)}, expected {self.dimension}"
                )
        return vectors
