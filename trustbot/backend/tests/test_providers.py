"""Tests for the embedding provider abstraction.

All offline: they exercise the deterministic hash provider and the factory's
selection logic, never the real model. This is what keeps CI fast and network-free
while still pinning the contract every provider must honor (fixed dimension,
L2-normalized, deterministic, order-preserving).
"""
import math

import pytest

from app.config import Settings, settings
from app.db.models import EMBEDDING_DIM
from app.providers import ProviderError, get_embedding_provider
from app.providers.hash_embedder import HashEmbeddingProvider


def test_default_provider_is_local():
    assert Settings.model_fields["embedding_provider"].default == "local"


def test_factory_selects_hash(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "hash")
    get_embedding_provider.cache_clear()
    try:
        assert isinstance(get_embedding_provider(), HashEmbeddingProvider)
    finally:
        get_embedding_provider.cache_clear()


def test_factory_rejects_unknown(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "nope")
    get_embedding_provider.cache_clear()
    try:
        with pytest.raises(ProviderError):
            get_embedding_provider()
    finally:
        get_embedding_provider.cache_clear()


def test_hash_provider_dimension():
    provider = HashEmbeddingProvider()
    [vec] = provider.embed_documents(["hello"])
    assert len(vec) == EMBEDDING_DIM


def test_hash_provider_is_normalized():
    provider = HashEmbeddingProvider()
    [vec] = provider.embed_documents(["some evidence text"])
    norm = math.sqrt(sum(x * x for x in vec))
    assert norm == pytest.approx(1.0, abs=1e-9)


def test_hash_provider_is_deterministic():
    provider = HashEmbeddingProvider()
    a = provider.embed_documents(["same input"])[0]
    b = provider.embed_documents(["same input"])[0]
    assert a == b


def test_hash_provider_distinguishes_text():
    provider = HashEmbeddingProvider()
    a = provider.embed_documents(["alpha"])[0]
    b = provider.embed_documents(["beta"])[0]
    assert a != b


def test_hash_provider_preserves_order():
    provider = HashEmbeddingProvider()
    batch = provider.embed_documents(["one", "two", "three"])
    assert batch[0] == provider.embed_query("one")
    assert batch[2] == provider.embed_query("three")
