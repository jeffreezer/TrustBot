"""Overlapping character-based chunking.

Character windows (not tokens) keep this dependency-free: tests and CI need no
tokenizer or model. Overlap preserves context that would otherwise be split across
a boundary. Deterministic: the same text and parameters always produce the same
chunks, which is what makes ingestion idempotent and testable.
"""
from __future__ import annotations


def chunk_text(text: str, *, size: int, overlap: int) -> list[str]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("chunk overlap must be >= 0 and < size")

    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    step = size - overlap
    chunks: list[str] = []
    n = len(text)
    for start in range(0, n, step):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append(piece)
        if start + size >= n:
            break  # last window already reached the end; avoid a trailing dup
    return chunks
