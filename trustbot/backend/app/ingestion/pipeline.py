"""Ingestion pipeline: bytes -> parse -> chunk -> embed -> knowledge_chunks.

Security invariants (CLAUDE.md):
  - ``org_id`` is required on every chunk — tenant scoping from day one.
  - Document content is treated as data, never instructions (see parse.py).
  - File size is validated at this boundary before any work is done.
  - Re-ingesting a source is idempotent: prior chunks for the exact
    (org_id, source_type, source_id) are deleted, then fresh ones inserted, so a
    re-run never duplicates or strands rows.

``build_chunk_rows`` is the pure, DB-free core (parse-free, just chunk+embed) so it
can be unit-tested with the deterministic hash provider; ``ingest_document`` adds
boundary validation and the idempotent database write.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import KnowledgeChunk
from ..providers import EmbeddingProvider, get_embedding_provider
from .chunk import chunk_text
from .parse import parse_document


class IngestionError(Exception):
    pass


def build_chunk_rows(
    *,
    org_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID | None,
    text: str,
    provider: EmbeddingProvider,
    meta: dict[str, Any] | None = None,
    size: int | None = None,
    overlap: int | None = None,
) -> list[dict[str, Any]]:
    """Chunk + embed text into KnowledgeChunk-shaped dicts. No DB access."""
    size = settings.chunk_size if size is None else size
    overlap = settings.chunk_overlap if overlap is None else overlap

    pieces = chunk_text(text, size=size, overlap=overlap)
    if not pieces:
        return []

    embeddings = provider.embed_documents(pieces)
    base_meta = dict(meta or {})
    return [
        {
            "org_id": org_id,
            "source_type": source_type,
            "source_id": source_id,
            "chunk_index": index,
            "chunk_text": piece,
            "embedding": embedding,
            "meta": {**base_meta, "char_len": len(piece)},
        }
        for index, (piece, embedding) in enumerate(zip(pieces, embeddings))
    ]


def _upsert_chunks(
    session: Session,
    *,
    org_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID | None,
    rows: list[dict[str, Any]],
) -> int:
    """Idempotent write: clear any prior chunks for this exact source, then insert."""
    stmt = delete(KnowledgeChunk).where(
        KnowledgeChunk.org_id == org_id,
        KnowledgeChunk.source_type == source_type,
    )
    stmt = stmt.where(
        KnowledgeChunk.source_id.is_(None)
        if source_id is None
        else KnowledgeChunk.source_id == source_id
    )
    session.execute(stmt)
    session.add_all(KnowledgeChunk(**row) for row in rows)
    session.flush()
    return len(rows)


def ingest_text(
    session: Session,
    *,
    org_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID | None,
    text: str,
    meta: dict[str, Any] | None = None,
    provider: EmbeddingProvider | None = None,
) -> int:
    """Chunk, embed, and persist already-extracted text (e.g. a DB row's fields).

    The structured-source counterpart to ``ingest_document``: controls and approved
    answers are rows, not files, so they skip the document parser but share the same
    chunk → embed → idempotent upsert path.
    """
    if org_id is None:
        raise IngestionError("org_id is required for ingestion (tenant scoping)")
    provider = provider or get_embedding_provider()
    rows = build_chunk_rows(
        org_id=org_id,
        source_type=source_type,
        source_id=source_id,
        text=text,
        provider=provider,
        meta=meta,
    )
    return _upsert_chunks(
        session, org_id=org_id, source_type=source_type, source_id=source_id, rows=rows
    )


def ingest_document(
    session: Session,
    *,
    org_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID | None,
    data: bytes,
    content_type: str | None = None,
    filename: str | None = None,
    meta: dict[str, Any] | None = None,
    provider: EmbeddingProvider | None = None,
) -> int:
    """Parse, chunk, embed, and persist a single document. Returns chunk count."""
    if org_id is None:
        raise IngestionError("org_id is required for ingestion (tenant scoping)")
    if len(data) > settings.max_ingest_bytes:
        raise IngestionError(
            f"document exceeds max ingest size "
            f"({len(data)} > {settings.max_ingest_bytes} bytes)"
        )

    text = parse_document(data, content_type=content_type, filename=filename)
    return ingest_text(
        session,
        org_id=org_id,
        source_type=source_type,
        source_id=source_id,
        text=text,
        meta=meta,
        provider=provider,
    )
