"""OpenAI-compatible embeddings via the standard /v1/embeddings endpoint.

A documented, config-selectable alternative (EMBEDDING_PROVIDER=api) for pointing
at a hosted or self-hosted embedding server (vLLM, TEI, OpenAI, etc.). Uses the
stdlib HTTP client to avoid pulling in another SDK / dependency. base_url and the
api_key are operator configuration, never untrusted request input; the key is
never logged.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import EmbeddingProvider, ProviderError


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        if not base_url:
            raise ProviderError("MODEL_BASE_URL is required for EMBEDDING_PROVIDER=api")
        if not model:
            raise ProviderError("EMBEDDING_MODEL is required for EMBEDDING_PROVIDER=api")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self._model, "input": list(texts)}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            f"{self._base_url}/embeddings", data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            # Surface a generic failure; do not echo headers (api key) into the message.
            raise ProviderError(f"embedding API request failed: {type(exc).__name__}") from exc
        items = sorted(body.get("data", []), key=lambda d: d.get("index", 0))
        return self._validate([item["embedding"] for item in items])
