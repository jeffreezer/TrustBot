"""Deterministic, dependency-free embedder for tests and offline CI.

Produces a stable pseudo-random unit vector from the text bytes alone — no model,
no network, no torch. Same input always yields the same vector, so tests can
assert on ingestion behavior without a multi-GB download. Not for production use:
the vectors carry no semantic meaning.
"""
from __future__ import annotations

import hashlib
import math

from .base import EmbeddingProvider


class HashEmbeddingProvider(EmbeddingProvider):
    name = "hash"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._validate([self._vector(t) for t in texts])

    def _vector(self, text: str) -> list[float]:
        data = text.encode("utf-8")
        out: list[float] = []
        counter = 0
        # Each sha256 digest yields 8 floats (32 bytes / 4); iterate until full.
        while len(out) < self.dimension:
            digest = hashlib.sha256(data + counter.to_bytes(4, "big")).digest()
            for i in range(0, len(digest), 4):
                if len(out) >= self.dimension:
                    break
                u = int.from_bytes(digest[i : i + 4], "big")
                out.append(u / 0xFFFFFFFF * 2.0 - 1.0)  # -> [-1, 1]
            counter += 1
        norm = math.sqrt(sum(x * x for x in out)) or 1.0
        return [x / norm for x in out]
