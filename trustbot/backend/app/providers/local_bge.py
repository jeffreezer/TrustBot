"""Local BGE-M3 embedder (CPU) — the default provider.

The heavy import (sentence-transformers / torch) is deferred to first use so that
importing this module, the ingestion pipeline, or the test suite costs nothing
when another provider is selected. The model is baked into the Docker image at
build time (see backend/Dockerfile), so runtime has no download and CPU inference
is expected at demo scale.
"""
from __future__ import annotations

from .base import EmbeddingProvider, ProviderError


class LocalBGEEmbeddingProvider(EmbeddingProvider):
    name = "local-bge-m3"

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None  # lazily loaded

    def _ensure_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - only hit without the dep
                raise ProviderError(
                    "sentence-transformers is required for EMBEDDING_PROVIDER=local; "
                    "install it or select another provider"
                ) from exc
            self._model = SentenceTransformer(self._model_name, device="cpu")
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        vectors = model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        )
        return self._validate([vec.tolist() for vec in vectors])
