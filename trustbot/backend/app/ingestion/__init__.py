"""Evidence ingestion: parse -> chunk -> embed -> knowledge_chunks (Phase 2)."""
from __future__ import annotations

from .chunk import chunk_text
from .parse import ParseError, UnsupportedDocumentError, parse_document
from .pipeline import IngestionError, build_chunk_rows, ingest_document

__all__ = [
    "chunk_text",
    "parse_document",
    "ParseError",
    "UnsupportedDocumentError",
    "build_chunk_rows",
    "ingest_document",
    "IngestionError",
]
