"""Reranker provider factory + the deterministic fakes used in tests/CI."""
import pytest

from app.config import settings
from app.providers import ProviderError, get_rerank_provider
from app.providers.lexical_reranker import LexicalRerankProvider
from app.providers.passthrough_reranker import PassthroughRerankProvider


def test_lexical_reranker_orders_by_query_overlap():
    reranker = LexicalRerankProvider()
    docs = [
        "Our retention policy covers backups.",
        "All data at rest is encrypted with AES-256.",
        "Employees complete annual security training.",
    ]
    order = reranker.rerank("Do you encrypt data at rest?", docs)
    assert order[0] == 1  # the encryption-at-rest doc ranks first


def test_lexical_reranker_is_deterministic():
    reranker = LexicalRerankProvider()
    docs = ["alpha beta", "gamma delta"]
    assert reranker.score("alpha", docs) == reranker.score("alpha", docs)


def test_lexical_reranker_empty_query_scores_zero():
    reranker = LexicalRerankProvider()
    assert reranker.score("?!", ["anything here"]) == [0.0]


def test_rerank_empty_documents_returns_empty():
    assert LexicalRerankProvider().rerank("q", []) == []


def test_passthrough_preserves_input_order():
    reranker = PassthroughRerankProvider()
    docs = ["first", "second", "third"]
    # Equal scores + stable sort => original order is kept.
    assert reranker.rerank("unrelated query", docs) == [0, 1, 2]


def test_factory_selects_hash(monkeypatch):
    monkeypatch.setattr(settings, "reranker_provider", "hash")
    get_rerank_provider.cache_clear()
    try:
        assert isinstance(get_rerank_provider(), LexicalRerankProvider)
    finally:
        get_rerank_provider.cache_clear()


def test_factory_selects_none_passthrough(monkeypatch):
    monkeypatch.setattr(settings, "reranker_provider", "none")
    get_rerank_provider.cache_clear()
    try:
        assert isinstance(get_rerank_provider(), PassthroughRerankProvider)
    finally:
        get_rerank_provider.cache_clear()


def test_factory_rejects_unknown(monkeypatch):
    monkeypatch.setattr(settings, "reranker_provider", "nope")
    get_rerank_provider.cache_clear()
    try:
        with pytest.raises(ProviderError):
            get_rerank_provider()
    finally:
        get_rerank_provider.cache_clear()


def test_default_reranker_provider_is_local():
    from app.config import Settings

    assert Settings.model_fields["reranker_provider"].default == "local"
