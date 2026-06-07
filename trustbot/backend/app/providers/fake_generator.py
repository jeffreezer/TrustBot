"""Deterministic, grounding-only generator for tests, offline CI, and the demo.

Not an LLM: it composes a structured respond-mode draft *only* from the retrieved grounding
using documented keyword cues, so it can never fabricate — if the grounding doesn't cover
the question it returns ``needs_input``. The same inputs always yield the same draft, which
is what keeps CI offline and the suite hermetic. Production should set
``GENERATION_PROVIDER=api``/``anthropic`` to point at a real model; this stand-in exercises
the whole validate → confidence → persist path without one.

Respond posture (05 §5-§7): the vendor answers for itself and puts its best honest foot
forward. A SOC 2 exception / open finding never downgrades an affirmation — it stays
``attested`` and the report self-contains the exception. The answers layer (confidence,
validators, fail-closed review) does the real safety work regardless of generator.
"""
from __future__ import annotations

import json
import re

from .generation_base import DraftRequest, GenerationProvider, GroundingDoc

# Relative authority for choosing which grounding doc to answer from. The canonical
# authority weights used for *confidence* live in answers/confidence.py; this is only a
# local tie-breaker for primary-source selection, so it need not match exactly.
_AUTHORITY_ORDER = {
    "policy": 5,
    "evidence": 5,
    "control": 4,
    "approved_answer": 3,
    "company_profile": 2,
}
# Honest-negative cues (scanned over the best-matching sentence of the primary chunk).
_NEGATIVE_CUES = (
    "not yet",
    "roadmap",
    "planned",
    "do not",
    "does not",
    "not supported",
    "not by default",
    "no public",
    "private disclosure only",
    "not offered",
    "not authorized",
)
# Vendor-scope cues → qualified (an affirmative the vendor would itself caveat — a scope,
# never an auditor finding).
_QUALIFIED_CUES = (
    "enterprise tier",
    "enterprise plan",
    "premium tier",
    "business tier",
    "add-on",
    "available on",
    "only on the",
    "upon request",
    "in the eu",
    "by region",
)
# Document-request classification (05 §7): a request to PROVIDE/SHARE an artifact.
_PROVISION_VERBS = (
    "provide",
    "share",
    "send",
    "furnish",
    "attach",
    "upload",
    "supply",
    "copy of",
    "give us",
    "make available",
    "may we obtain",
    "can we see",
)
_DOC_NOUNS = (
    "report",
    "certificate",
    "certification",
    "attestation",
    "soc 2",
    "soc2",
    "pentest",
    "penetration test",
    "audit",
    "letter",
    "aoc",
    "documentation",
    "iso 27001",
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by do does for from how in is it of on or our that the to "
    "we what when where which who why with you your is".split()
)


def _terms(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2}


def _clean(text: str) -> str:
    """Drop Markdown heading/bullet markup and collapse whitespace into readable prose."""
    lines = []
    for raw in text.split("\n"):
        line = raw.strip().lstrip("#").lstrip("-").strip()
        if line:
            lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _first_sentence(text: str) -> str:
    cleaned = _clean(text)
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return parts[0].strip() if parts else cleaned


def _is_document_request(question: str) -> bool:
    low = question.lower()
    return any(v in low for v in _PROVISION_VERBS) and any(n in low for n in _DOC_NOUNS)


class FakeGenerationProvider(GenerationProvider):
    name = "fake"

    def draft(self, request: DraftRequest) -> str:
        grounding = request.grounding
        requires_document = _is_document_request(request.question)
        if not grounding:
            return self._needs_input("No supporting evidence was retrieved for the question.")

        q_terms = _terms(request.question)
        # Primary = most query-term overlap; ties broken by source authority, so when
        # redundant sources cover the same fact the authoritative one wins (a policy
        # beats a vague approved answer — the Phase 3 data-classification lesson).
        order = sorted(
            range(len(grounding)),
            key=lambda i: (
                len(q_terms & _terms(grounding[i].text)),
                _AUTHORITY_ORDER.get(grounding[i].source_type, 1),
                -i,
            ),
            reverse=True,
        )
        primary = grounding[order[0]]
        if q_terms and not (q_terms & _terms(primary.text)):
            return self._needs_input("Retrieved evidence does not address the question.")

        # Read the outcome from the PRIMARY chunk only, and from the *sentence that best
        # matches the question* — so a tangential caveat elsewhere in the chunk can't flip
        # it. An approved answer's own "A: Yes/No" takes precedence. A SOC 2 exception /
        # open finding does NOT downgrade — respond posture keeps the affirmation.
        polarity = self._approved_polarity(primary)
        answer_sentence = self._best_sentence(primary.text, q_terms)
        if polarity == "no" or (
            polarity is None and any(c in answer_sentence for c in _NEGATIVE_CUES)
        ):
            outcome, prefix = "negative", "No."
            scope = ""
        elif any(c in answer_sentence for c in _QUALIFIED_CUES):
            outcome, prefix = "qualified", "Yes, within scope."
            scope = self._sentence_with_cue(grounding, _QUALIFIED_CUES)
        else:
            outcome, prefix = "attested", "Yes."
            scope = ""

        scored = [grounding[i] for i in order]
        # Synthesize over the top-k: cite the primary plus any corroborating doc that
        # shares query terms — preferring authoritative sources — not just the #1 chunk.
        refs = [primary.ref]
        for g in scored[1:]:
            if len(refs) >= 3:
                break
            if q_terms & _terms(g.text):
                refs.append(g.ref)

        claim = _first_sentence(primary.text)
        body = _clean(primary.text)
        draft = {
            "outcome": outcome,
            "short_answer": f"{prefix} {claim}".strip(),
            "answer": f"{prefix} {body}".strip(),
            "claim": claim,
            "scope": scope,
            "evidence_refs": refs,
            "requires_document": requires_document,
        }
        return json.dumps(draft)

    @staticmethod
    def _best_sentence(text: str, q_terms: set[str]) -> str:
        """The lowercased sentence in ``text`` that best matches the question terms."""
        sentences = re.split(r"(?<=[.!?])\s+", _clean(text)) or [_clean(text)]
        if not q_terms:
            return sentences[0].lower()
        return max(sentences, key=lambda s: len(q_terms & _terms(s))).lower()

    @staticmethod
    def _approved_polarity(doc: GroundingDoc) -> str | None:
        """For an approved answer, read its own 'A: Yes/No' as the outcome polarity."""
        if doc.source_type != "approved_answer":
            return None
        m = re.search(r"\ba:\s*(yes|no)\b", doc.text.lower())
        return m.group(1) if m else None

    @staticmethod
    def _needs_input(reason: str) -> str:
        return json.dumps(
            {
                "outcome": "needs_input",
                "short_answer": "",
                "answer": "",
                "claim": "",
                "scope": "",
                "evidence_refs": [],
                "requires_document": False,
                "model_note": reason,
            }
        )

    @staticmethod
    def _sentence_with_cue(grounding: tuple[GroundingDoc, ...], cues: tuple[str, ...]) -> str:
        for g in grounding:
            for sentence in re.split(r"(?<=[.!?])\s+", _clean(g.text)):
                low = sentence.lower()
                if any(cue in low for cue in cues):
                    return sentence.strip()
        return ""
