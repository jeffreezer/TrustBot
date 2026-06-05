"""Local cross-encoder reranker (default): ms-marco-MiniLM on CPU.

The model is small and runs fine on CPU, so the demo needs no GPU. It is baked into
the image at build time (see Dockerfile) — no first-request download, no runtime
network. The heavy ``sentence_transformers`` import is deferred to first use.
"""
from __future__ import annotations

from .rerank_base import RerankProvider


class LocalCrossEncoderRerankProvider(RerankProvider):
    name = "local-cross-encoder"

    def __init__(self, model_name: str, revision: str | None = None) -> None:
        self._model_name = model_name
        self._revision = revision or None  # pin to an exact upstream commit when set
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self._model_name, revision=self._revision, device="cpu"
            )
        return self._model

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        model = self._ensure_model()
        pairs = [(query, doc) for doc in documents]
        return [float(s) for s in model.predict(pairs)]
