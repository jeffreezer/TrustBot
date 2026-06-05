"""Provider factory — selects the embedding backend from EMBEDDING_PROVIDER.

Callers do ``from app.providers import get_embedding_provider`` and never import a
concrete provider, so the rest of the app stays model-agnostic. Concrete providers
(and their heavy imports) are loaded lazily, only when selected.
"""
from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import EmbeddingProvider, ProviderError
from .rerank_base import RerankProvider


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    choice = settings.embedding_provider.strip().lower()
    if choice == "local":
        from .local_bge import LocalBGEEmbeddingProvider

        return LocalBGEEmbeddingProvider(settings.embedding_model)
    if choice == "hash":
        from .hash_embedder import HashEmbeddingProvider

        return HashEmbeddingProvider()
    if choice == "api":
        from .openai_api import OpenAICompatibleEmbeddingProvider

        return OpenAICompatibleEmbeddingProvider(
            settings.model_base_url, settings.model_api_key, settings.embedding_model
        )
    raise ProviderError(f"unknown EMBEDDING_PROVIDER: {settings.embedding_provider!r}")


@lru_cache(maxsize=1)
def get_rerank_provider() -> RerankProvider:
    choice = settings.reranker_provider.strip().lower()
    if choice == "local":
        from .local_cross_encoder import LocalCrossEncoderRerankProvider

        return LocalCrossEncoderRerankProvider(settings.reranker_model)
    if choice == "hash":
        from .lexical_reranker import LexicalRerankProvider

        return LexicalRerankProvider()
    if choice == "none":
        from .passthrough_reranker import PassthroughRerankProvider

        return PassthroughRerankProvider()
    raise ProviderError(f"unknown RERANKER_PROVIDER: {settings.reranker_provider!r}")


__all__ = [
    "EmbeddingProvider",
    "RerankProvider",
    "ProviderError",
    "get_embedding_provider",
    "get_rerank_provider",
]
