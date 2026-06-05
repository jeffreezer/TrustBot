"""Structure-aware chunking + front-matter extraction — DB-free tests.

These pin the retrieval-quality fix: a policy's leading boilerplate (title block,
disclaimer, ``> metadata``) must not be embedded as body text, and Markdown is split
on section headings so each section is its own coherent chunk — with a window-chunk
fallback so messier sources never regress.
"""
import uuid

from app.ingestion import (
    build_chunk_rows,
    chunk_document,
    extract_front_matter,
    split_sections,
)
from app.providers.hash_embedder import HashEmbeddingProvider

POLICY = """# Northwind AI — Data Classification & Handling Policy

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the profile.
> **Owner:** Head of GRC · **Version:** 2.0 · **Approved:** 2025-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** C1.1, C1.2, DSP (catalog)

## 1. Purpose

Establish how Northwind classifies and handles data according to sensitivity.

## 2. Scope

All data created, processed, or stored by Northwind, including customer content.

## 3. Classification Tiers

- **Public** — intended for public release.
- **Internal** — internal business information.
- **Confidential** — customer content, credentials, sensitive business data.
- **Restricted** — secrets, encryption keys, regulated data.
"""


# --- heading split ----------------------------------------------------------

def test_heading_split_one_chunk_per_section():
    # The pipeline strips front-matter first, then chunks the body; mirror that here.
    body, _ = extract_front_matter(POLICY)
    chunks = chunk_document(body, size=2000, overlap=100)
    # 3 "## N." sections (no standalone preamble; the title is just a prefix).
    assert len(chunks) == 3
    headings = ["## 1. Purpose", "## 2. Scope", "## 3. Classification Tiers"]
    for chunk, heading in zip(chunks, headings):
        assert heading in chunk
    # Each section carries the document title as context, and the tiers stay together.
    assert all(c.startswith("# Northwind AI") for c in chunks)
    tiers = chunks[2]
    assert all(t in tiers for t in ("Public", "Internal", "Confidential", "Restricted"))


def test_oversized_section_falls_back_to_window_chunking():
    # One heading + a body far larger than the cap → that section is window-chunked.
    big = "# Doc\n\n## Big Section\n\n" + ("word " * 400)
    chunks = chunk_document(big, size=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_headingless_input_falls_back_cleanly():
    plain = "Just some prose. " * 60  # no headings at all
    sectioned = split_sections(plain)
    assert sectioned == []  # signals fallback
    chunks = chunk_document(plain, size=150, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 150 for c in chunks)


def test_non_markdown_structured_text_is_single_chunk():
    # An approved-answer style blob: no headings, under the cap → unchanged.
    text = "Q: Is data encrypted at rest?\n\nA: Yes\n\nAES-256 at rest."
    assert chunk_document(text, size=1200, overlap=100) == [text]


# --- front-matter -----------------------------------------------------------

def test_front_matter_excluded_from_body_but_kept_as_metadata():
    body, fm = extract_front_matter(POLICY)

    # Routed to metadata.
    assert fm["owner"] == "Head of GRC"
    assert fm["version"] == "2.0"
    assert fm["classification"].startswith("Internal — customer-shareable")
    assert fm["related_controls"] == "C1.1, C1.2, DSP (catalog)"

    # Excluded from embedded body: no blockquote, no disclaimer, no metadata lines.
    assert ">" not in body
    assert "SYNTHETIC" not in body
    assert "Owner:" not in body
    assert "Classification:" not in body

    # Title and section headings remain — useful semantic signal.
    assert body.startswith("# Northwind AI — Data Classification & Handling Policy")
    assert "## 3. Classification Tiers" in body


def test_no_front_matter_leaves_text_untouched():
    text = "# Title\n\n## Section\n\nBody with no blockquote."
    body, fm = extract_front_matter(text)
    assert fm == {}
    assert body == text


def test_disclaimer_without_metadata_is_dropped_with_empty_front_matter():
    # A lone blockquote disclaimer (no "Key: value") → stripped, nothing to route.
    text = "# Whitepaper\n\n> **SYNTHETIC / FICTIONAL.** A demo document.\n\n## Overview\n\nBody."
    body, fm = extract_front_matter(text)
    assert fm == {}
    assert "SYNTHETIC" not in body
    assert body.startswith("# Whitepaper")
    assert "## Overview" in body


# --- build_chunk_rows integration ------------------------------------------

def test_build_rows_routes_front_matter_into_chunk_meta():
    rows = build_chunk_rows(
        org_id=uuid.uuid4(),
        source_type="policy",
        source_id=uuid.uuid4(),
        text=POLICY,
        provider=HashEmbeddingProvider(),
        meta={"title": "Data Classification & Handling Policy"},
        size=2000,
        overlap=100,
    )
    assert rows
    first = rows[0]
    # Caller meta preserved; front-matter attached; boilerplate never embedded.
    assert first["meta"]["title"] == "Data Classification & Handling Policy"
    assert first["meta"]["front_matter"]["owner"] == "Head of GRC"
    assert "SYNTHETIC" not in first["chunk_text"]
    assert all("> **Owner:**" not in r["chunk_text"] for r in rows)
