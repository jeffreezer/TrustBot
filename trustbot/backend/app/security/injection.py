"""Prompt-injection detection + neutralization (Phase 8, layer 2 — the boundary screen).

This is the OUTER, weakest layer of the injection defense — a deterministic, offline
heuristic, not the real protection. The real defense is architectural: untrusted text reaches
the model strictly as fenced DATA (layer 1), read-only org-scoped tools (layer 3), and the
deterministic output validators + human approval (layer 4). This module's job is to *surface*
injection-like content so it can be flagged (respond mode) or quarantined (review mode), and
to *neutralize* it (strip obfuscation, redact the matched directive) so it never reaches the
model as a live instruction even though it was already inert as data.

No model, no network — pure regex + Unicode normalization, so it runs in offline CI.
Detection is conservative and explainable; a match means "a human should look", never "block".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Zero-width / invisible characters used to obfuscate ("i​gnore instructions"), plus the
# BOM and word-joiner. Stripped before matching so obfuscation can't slip past the patterns.
_ZERO_WIDTH = (
    "​"  # zero-width space
    "‌"  # zero-width non-joiner
    "‍"  # zero-width joiner
    "⁠"  # word joiner
    "﻿"  # BOM / zero-width no-break space
    "­"  # soft hyphen
    "᠎"  # Mongolian vowel separator
)
_ZERO_WIDTH_RE = re.compile(f"[{_ZERO_WIDTH}]")
# Other format/control characters (bidi overrides, etc.) — stripped as obfuscation.
_BIDI = "‪‫‬‭‮⁦⁧⁨⁩"
_BIDI_RE = re.compile(f"[{_BIDI}]")

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Categorized injection patterns. Each entry is (category, compiled regex). Kept narrow and
# explainable; they screen DATA, so a match routes to a human — it never executes.
_PATTERN_SPECS: tuple[tuple[str, str], ...] = (
    # Instruction-override
    ("override", r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|messages?|rules?|context)"),
    ("override", r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding|system)"),
    ("override", r"forget\s+(?:everything|all|the\s+above|previous|prior|your\s+instructions)"),
    ("override", r"override\s+(?:your\s+|the\s+)?(?:instructions|rules|system|prompt|guardrails)"),
    ("override", r"new\s+instructions?\s*:"),
    ("override", r"(?:from\s+now\s+on|going\s+forward)[, ]+(?:you|ignore|act|respond)"),
    # Role / persona override
    ("role_override", r"you\s+are\s+now\b"),
    ("role_override", r"pretend\s+to\s+be\b"),
    ("role_override", r"act\s+as\s+(?:if|a|an|though)\b"),
    ("role_override", r"\b(?:dan|do\s+anything\s+now|jailbreak)\b"),
    ("role_override", r"you\s+are\s+(?:a|an)\s+(?:unrestricted|uncensored|developer\s+mode)"),
    # System-prompt directive injection
    ("system_directive", r"(?:^|\n)\s*system\s*:"),
    ("system_directive", r"\bsystem\s+prompt\b"),
    ("system_directive", r"<\s*/?\s*(?:system|assistant|instructions?)\s*>"),
    ("system_directive", r"\[\s*(?:system|assistant|inst)\s*\]"),
    # Tool / command directive
    ("tool_directive", r"\bexecute\s+(?:the\s+)?(?:following|this)\s+(?:command|tool|code)"),
    ("tool_directive", r"\b(?:run|call|invoke)\s+(?:the\s+)?(?:tool|command|function|shell)\b"),
    # Data / system-prompt exfiltration
    ("exfiltration", r"(?:print|repeat|reveal|show|output|disclose|leak)\s+(?:your\s+|the\s+|all\s+)?(?:system\s+prompt|instructions|guidelines|rules|configuration)"),
    ("exfiltration", r"what\s+(?:are|were)\s+your\s+(?:system\s+)?(?:instructions|prompt|rules)"),
    ("exfiltration", r"(?:send|exfiltrate|post|email|upload|transmit)\s+(?:the\s+|this\s+|all\s+)?(?:data|content|secrets?|keys?|credentials?)\s+to\b"),
    ("exfiltration", r"\bbase64\b.*(?:encode|decode).*(?:prompt|instructions|secret)"),
    # Compliance-manipulation (the canonical "mark us compliant" attack)
    ("manipulation", r"(?:mark|rate|score|declare|certify)\s+(?:us|this|the\s+vendor|everything|all)\s+(?:as\s+)?(?:compliant|approved|passed|secure|certified)"),
    ("manipulation", r"do\s+not\s+(?:tell|inform|alert|flag)\s+(?:the\s+)?(?:user|human|reviewer|analyst)"),
)
_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (cat, re.compile(pat, re.IGNORECASE)) for cat, pat in _PATTERN_SPECS
)

_SNIPPET_MAX = 160
REDACTION_MARKER = "⟦redacted-injection⟧"
_REDACTION = REDACTION_MARKER
_ALNUM_RE = re.compile(r"[a-z0-9]", re.IGNORECASE)


def has_substance(text: str) -> bool:
    """True if neutralized text still has answerable content (alphanumerics that aren't part
    of a redaction marker) — i.e. it wasn't a pure injection that left nothing behind."""
    return bool(_ALNUM_RE.search((text or "").replace(REDACTION_MARKER, " ")))


@dataclass(frozen=True)
class InjectionFinding:
    """The outcome of screening one piece of untrusted text. Metadata-only: ``snippet`` is a
    short, truncated excerpt for the human reviewer (shown in the UI, never dumped to server
    logs); ``categories`` names the matched attack classes."""

    categories: tuple[str, ...]
    snippet: str
    match_count: int = 0
    from_obfuscation: bool = False
    extras: tuple[str, ...] = field(default_factory=tuple)  # e.g. "html_comment", "filename"


def normalize_text(text: str) -> str:
    """NFKC-normalize and strip zero-width / bidi / soft-hyphen obfuscation, so an attacker
    can't hide a directive with invisible characters or homoglyph spacing."""
    if not text:
        return ""
    cleaned = _ZERO_WIDTH_RE.sub("", text)
    cleaned = _BIDI_RE.sub("", cleaned)
    return unicodedata.normalize("NFKC", cleaned)


def _scan(text: str) -> tuple[set[str], int]:
    """Return (matched categories, total match count) for the given (already-normalized) text."""
    categories: set[str] = set()
    count = 0
    for category, regex in _COMPILED:
        found = regex.findall(text)
        if found:
            categories.add(category)
            count += len(found)
    return categories, count


def screen(text: str, *, filename: str | None = None) -> InjectionFinding | None:
    """Screen untrusted text (a question, a chunk, a document). Returns an ``InjectionFinding``
    if injection-like content is present, else ``None``.

    Screens both the normalized text (de-obfuscated) and HTML comments / hidden markup, plus an
    optional filename. ``from_obfuscation`` records that the hit only appeared after stripping
    zero-width characters — itself a strong signal of intent."""
    if not text and not filename:
        return None

    raw = text or ""
    normalized = normalize_text(raw)
    categories: set[str] = set()
    extras: list[str] = []
    count = 0

    # 1) Main scan over the de-obfuscated text.
    cats, c = _scan(normalized)
    categories |= cats
    count += c
    from_obfuscation = bool(cats) and not _scan(raw)[0]

    # 2) HTML comments / hidden markup carry their own directives ("<!-- ignore ... -->").
    comments = _HTML_COMMENT_RE.findall(raw)
    if comments:
        ccats, cc = _scan(normalize_text(" ".join(comments)))
        if ccats:
            categories |= ccats
            count += cc
            extras.append("html_comment")

    # 3) Filename screen (a poisoned filename is a known indirect vector). Separators
    # (_ - . +) are normalized to spaces so "ignore_all_previous_instructions.md" is caught.
    if filename:
        fname = re.sub(r"[_\-.+]+", " ", normalize_text(filename))
        fcats, fc = _scan(fname)
        if fcats:
            categories |= fcats
            count += fc
            extras.append("filename")

    if not categories:
        return None

    snippet = _make_snippet(normalized or filename or "")
    return InjectionFinding(
        categories=tuple(sorted(categories)),
        snippet=snippet,
        match_count=count,
        from_obfuscation=from_obfuscation,
        extras=tuple(extras),
    )


def screen_filename(filename: str | None) -> InjectionFinding | None:
    """Screen just a filename (uploads can carry a directive in the name)."""
    if not filename:
        return None
    return screen("", filename=filename)


def _make_snippet(text: str) -> str:
    """A short, single-line excerpt around the first matched directive (for the reviewer UI)."""
    for _category, regex in _COMPILED:
        m = regex.search(text)
        if m:
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            excerpt = " ".join(text[start:end].split())
            if len(excerpt) > _SNIPPET_MAX:
                excerpt = excerpt[:_SNIPPET_MAX] + "…"
            return excerpt
    return " ".join(text.split())[:_SNIPPET_MAX]


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def neutralize(text: str) -> str:
    """Render injection-like content inert before it reaches the model: strip obfuscation, drop
    HTML comments, and REDACT any sentence containing a matched directive (not just the matched
    phrase — so a trailing payload like "...and say we are HIPAA certified" goes with it),
    leaving the surrounding legitimate content intact. Defense in depth: the text was already
    inert as fenced data; this guarantees the live directive never enters the prompt."""
    if not text:
        return ""
    cleaned = normalize_text(_HTML_COMMENT_RE.sub(" ", text))
    out: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(cleaned):
        if not sentence.strip():
            continue
        if any(regex.search(sentence) for _c, regex in _COMPILED):
            if out and out[-1] == _REDACTION:
                continue  # collapse consecutive redactions
            out.append(_REDACTION)
        else:
            out.append(sentence)
    return " ".join(out).strip()


def detect_injection(text: str) -> bool:
    """Backwards-compatible boolean screen (True == injection-like content present)."""
    return screen(text) is not None
