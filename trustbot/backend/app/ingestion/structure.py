"""Structure-aware Markdown chunking + front-matter extraction.

Splitting on section headings keeps each chunk topically coherent — the embedding
and the cross-encoder see one subject, not a fixed window that may straddle a section
boundary or be dominated by a document's header boilerplate. (That boilerplate is
exactly what sank the data-classification policy in retrieval: a 1,200-char window
led by the title block, the disclaimer, and the ``>`` metadata diluted the tiers.)

Two fallbacks keep this from ever doing *worse* than the plain window chunker: a
section larger than the size cap is window-chunked, and a document without usable
heading structure (tables, questionnaire-derived text, future PDFs) is window-chunked
whole. Heading-aware is the primary path; ``chunk_text`` is the floor.

Security: this only parses and slices text. Document content is data, never
instructions (see parse.py) — nothing here interprets, executes, or follows it.
"""
from __future__ import annotations

import re
from collections import Counter

from .chunk import chunk_text

_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
# A front-matter "**Key:** value" pair, anchored at the segment start. The key is a
# short word phrase, so a stray colon inside prose (which has no leading key) won't
# match — that's how the disclaimer line is dropped rather than parsed.
_FRONT_MATTER_KV_RE = re.compile(r"^\*{0,2}([A-Za-z][\w /-]*?)\*{0,2}:\*{0,2}\s*(.+)$")
# In these documents, multiple metadata pairs share one blockquote line, separated
# by a middot: "**Owner:** … · **Version:** … · **Approved:** …".
_SEGMENT_SEP = "·"


def _is_h1(line: str) -> bool:
    return line.lstrip().startswith("# ")


def _normalize_key(key: str) -> str:
    return re.sub(r"\s+", "_", key.strip().lower())


def extract_front_matter(text: str) -> tuple[str, dict[str, str]]:
    """Split a leading metadata block off the body: returns ``(body, front_matter)``.

    Front-matter is the contiguous run of Markdown blockquote (``>``) lines at the very
    top of the document, after an optional ``# title`` — the disclaimer and any
    ``**Key:** value`` metadata. Those are routed to metadata, not embedded: they're
    boilerplate that dilutes a chunk's topical signal. The ``# title`` and every section
    heading stay in the body, where they are useful retrieval signal.

    General by design: it keys on Markdown structure (a leading blockquote), never on
    any specific wording, so a real customer policy with the same header shape works.
    """
    lines = text.split("\n")
    n = len(lines)

    i = 0
    while i < n and not lines[i].strip():
        i += 1
    # Keep a leading H1 title in the body; it is the document's strongest label.
    title_end = i + 1 if i < n and _is_h1(lines[i]) else i
    j = title_end
    while j < n and not lines[j].strip():
        j += 1

    block_start = j
    block_end = j
    while block_end < n and lines[block_end].lstrip().startswith(">"):
        block_end += 1
    if block_end == block_start:
        return text, {}  # no leading blockquote → nothing to route out

    front_matter: dict[str, str] = {}
    for raw in lines[block_start:block_end]:
        line = raw.lstrip()
        line = line[1:].strip() if line.startswith(">") else line.strip()
        for segment in line.split(_SEGMENT_SEP):
            m = _FRONT_MATTER_KV_RE.match(segment.strip())
            if m:
                front_matter[_normalize_key(m.group(1))] = m.group(2).strip()

    body = "\n".join(lines[:title_end] + lines[block_end:]).strip()
    return body, front_matter


def _choose_split_level(levels: list[int]) -> int:
    """The shallowest heading level that repeats — the document's section level.

    A lone ``# title`` over several ``##`` sections splits at ``##``. If no level
    repeats, split at the shallowest heading present (degenerate docs collapse toward
    a single section, which the size cap then window-chunks).
    """
    counts = Counter(levels)
    repeated = sorted(level for level, count in counts.items() if count >= 2)
    return repeated[0] if repeated else min(levels)


def split_sections(text: str) -> list[str]:
    """Split Markdown into one chunk per section heading at the primary section level.

    Returns ``[]`` when the document has fewer than two headings (no usable structure)
    so the caller falls back to window chunking. The H1 title is prepended to each
    section as lightweight context, so a section chunk still names its document.
    """
    lines = text.split("\n")
    headings = [
        (idx, len(m.group(1)))
        for idx, line in enumerate(lines)
        if (m := _HEADING_RE.match(line))
    ]
    if len(headings) < 2:
        return []

    split_level = _choose_split_level([level for _, level in headings])
    split_points = [idx for idx, level in headings if level == split_level]
    title_line = lines[headings[0][0]].strip() if headings[0][1] == 1 else ""

    def with_title(block: str) -> str:
        block = block.strip()
        if title_line and block and not block.lstrip().startswith(title_line):
            return f"{title_line}\n\n{block}"
        return block

    sections: list[str] = []
    preamble = "\n".join(lines[: split_points[0]]).strip()
    if title_line and preamble.startswith(title_line):
        preamble = preamble[len(title_line):].strip()
    if preamble:
        sections.append(with_title(preamble))

    bounds = split_points + [len(lines)]
    for start, end in zip(bounds, bounds[1:]):
        section = "\n".join(lines[start:end]).strip()
        if section:
            sections.append(with_title(section))
    return [s for s in sections if s]


def chunk_document(text: str, *, size: int, overlap: int) -> list[str]:
    """Heading-aware chunking with a window-chunk fallback.

    Primary path: one chunk per section. Fallbacks (never worse than the plain window
    chunker): a section longer than ``size`` is window-chunked, and a document without
    usable headings is window-chunked whole.
    """
    text = text.strip()
    if not text:
        return []
    sections = split_sections(text)
    if not sections:
        return chunk_text(text, size=size, overlap=overlap)

    chunks: list[str] = []
    for section in sections:
        if len(section) <= size:
            chunks.append(section)
        else:
            chunks.extend(chunk_text(section, size=size, overlap=overlap))
    return chunks
