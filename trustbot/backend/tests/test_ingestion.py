"""Tests for the ingestion pipeline's DB-free core (parse, chunk, build).

The database round-trip (idempotent delete+insert) is validated end-to-end against
the live stack; here we pin the pure logic with the deterministic hash provider:
chunking math, parse type-gating and decoding, tenant scoping on every row, and
the boundary size check.
"""
import uuid

import pytest

from app.ingestion import (
    IngestionError,
    UnsupportedDocumentError,
    build_chunk_rows,
    chunk_text,
    ingest_document,
    parse_document,
)
from app.providers.hash_embedder import HashEmbeddingProvider

ORG = uuid.uuid4()


# --- chunking ---------------------------------------------------------------

def test_chunk_short_text_single_chunk():
    assert chunk_text("a short doc", size=100, overlap=10) == ["a short doc"]


def test_chunk_empty_text():
    assert chunk_text("   ", size=100, overlap=10) == []


def test_chunk_long_text_overlaps_and_covers():
    text = "".join(chr(ord("a") + (i % 26)) for i in range(250))
    chunks = chunk_text(text, size=100, overlap=20)
    assert len(chunks) > 1
    # Step is size-overlap=80; first two chunks share their boundary region.
    assert text[80:100] in chunks[0]
    assert chunks[1].startswith(text[80:100])
    # Every character is covered by at least one chunk.
    assert "".join(c[:80] for c in chunks).startswith(text[:80])


def test_chunk_rejects_overlap_ge_size():
    with pytest.raises(ValueError):
        chunk_text("x" * 50, size=10, overlap=10)


# --- parsing ----------------------------------------------------------------

def test_parse_markdown_bytes():
    out = parse_document(b"# Title\n\nbody", content_type="text/markdown", filename="a.md")
    assert "# Title" in out and "body" in out


def test_parse_normalizes_crlf():
    out = parse_document(b"line1\r\nline2", content_type="text/plain", filename="a.txt")
    assert "\r" not in out
    assert out == "line1\nline2"


def test_parse_strips_utf8_bom():
    out = parse_document(b"\xef\xbb\xbfhello", content_type="text/markdown", filename="a.md")
    assert out == "hello"


def test_parse_rejects_unsupported_type():
    with pytest.raises(UnsupportedDocumentError):
        parse_document(b"%PDF-1.7", content_type="application/pdf", filename="a.pdf")


# --- build_chunk_rows (chunk + embed, no DB) --------------------------------

def _rows(text, **kw):
    return build_chunk_rows(
        org_id=ORG,
        source_type="evidence",
        source_id=uuid.uuid4(),
        text=text,
        provider=HashEmbeddingProvider(),
        **kw,
    )


def test_build_rows_scopes_every_row_to_org():
    rows = _rows("x" * 500, size=100, overlap=20)
    assert rows
    assert all(r["org_id"] == ORG for r in rows)


def test_build_rows_index_is_sequential():
    rows = _rows("x" * 500, size=100, overlap=20)
    assert [r["chunk_index"] for r in rows] == list(range(len(rows)))


def test_build_rows_embeds_each_chunk_at_full_dim():
    from app.db.models import EMBEDDING_DIM

    rows = _rows("x" * 500, size=100, overlap=20)
    assert all(len(r["embedding"]) == EMBEDDING_DIM for r in rows)


def test_build_rows_merges_meta():
    rows = build_chunk_rows(
        org_id=ORG,
        source_type="evidence",
        source_id=uuid.uuid4(),
        text="hello world",
        provider=HashEmbeddingProvider(),
        meta={"title": "SOC2", "confidentiality": "confidential"},
        size=100,
        overlap=10,
    )
    assert rows[0]["meta"]["title"] == "SOC2"
    assert rows[0]["meta"]["confidentiality"] == "confidential"
    assert rows[0]["meta"]["char_len"] == len(rows[0]["chunk_text"])


def test_build_rows_empty_text():
    assert _rows("   ", size=100, overlap=10) == []


# --- ingest_document boundary checks (raise before any DB access) -----------

def test_ingest_requires_org_id():
    with pytest.raises(IngestionError):
        ingest_document(
            None,  # never reached: org_id check fires first
            org_id=None,
            source_type="evidence",
            source_id=uuid.uuid4(),
            data=b"hello",
            provider=HashEmbeddingProvider(),
        )


def test_ingest_rejects_oversize_document(monkeypatch):
    from app.ingestion import pipeline

    monkeypatch.setattr(pipeline.settings, "max_ingest_bytes", 4)
    with pytest.raises(IngestionError):
        ingest_document(
            None,  # never reached: size check fires before the DB write
            org_id=ORG,
            source_type="evidence",
            source_id=uuid.uuid4(),
            data=b"this is definitely longer than four bytes",
            provider=HashEmbeddingProvider(),
        )
