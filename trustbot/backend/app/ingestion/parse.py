"""Document parsing — bytes to plain text.

Security: parsed content is **data, never instructions** (CLAUDE.md). This module
only decodes and normalizes text; it never interprets, executes, or follows links
inside a document. Phase 2 handles text/markdown only — PDF/Office parsing arrives
in a later phase, and unsupported types are rejected at this boundary rather than
silently mishandled.
"""
from __future__ import annotations

from pathlib import Path


class ParseError(Exception):
    pass


class UnsupportedDocumentError(ParseError):
    """The document's type is not handled by the Phase 2 text ingestion path."""


_TEXT_CONTENT_TYPES = {
    "text/markdown",
    "text/x-markdown",
    "text/plain",
    "text/csv",
    "application/json",
}
_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".csv", ".json"}


def _looks_textual(content_type: str, suffix: str) -> bool:
    return (
        content_type.startswith("text/")
        or content_type in _TEXT_CONTENT_TYPES
        or suffix in _TEXT_SUFFIXES
    )


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    # Last resort: never raise on stray bytes, but don't fabricate content either.
    return data.decode("utf-8", errors="replace")


def parse_document(
    data: bytes, *, content_type: str | None = None, filename: str | None = None
) -> str:
    """Decode an evidence document to normalized plain text.

    Requires an affirmative text signal (content type or extension); binary
    document types raise ``UnsupportedDocumentError`` so they fail loudly here.
    """
    content_type = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename).suffix.lower() if filename else ""
    if not _looks_textual(content_type, suffix):
        raise UnsupportedDocumentError(
            f"unsupported document type for ingestion "
            f"(content_type={content_type!r}, filename={filename!r})"
        )
    text = _decode(data)
    # Normalize line endings; the chunker works on a single canonical newline form.
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()
