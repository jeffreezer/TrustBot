"""Composite answer confidence — explicitly NOT the rerank score.

The cross-encoder rerank score measures query↔chunk *relevance* only; it is an
uncalibrated, source-blind logit, so it must never be the answer's confidence or the
human-review trigger on its own (a verbatim statement in an authoritative policy can
carry a modest rerank logit yet deserve high confidence). Confidence here is a composite
of four signals:

  relevance  — squashed rerank of the cited chunks (a soft term, never a gate)
  authority  — source_type weight (policy / SOC 2 evidence / control / approved answer
               are authoritative; the company profile less so)
  agreement  — how many independent source documents corroborate the claim
  coverage   — do the cited chunks actually contain the salient terms of the question

Weights deliberately let authority + coverage dominate, so "stated verbatim in an
authoritative policy" resolves to HIGH even when the rerank logit is modest.
"""
from __future__ import annotations

import math
import re
from collections.abc import Sequence

from .schema import CitedEvidence, ConfidenceBand

# Authority by source_type. approved_answer is high but below a primary source: per
# principle 7 it is a reusable *candidate*, re-validated against current evidence, not an
# authoritative bypass — so it never alone reaches the top authority of a policy/evidence.
SOURCE_AUTHORITY: dict[str, float] = {
    "policy": 1.0,
    "evidence": 1.0,
    "control": 0.85,
    "approved_answer": 0.9,
    "company_profile": 0.7,
}
_DEFAULT_AUTHORITY = 0.5

# Component weights (sum to 1.0). Authority + coverage dominate by design.
_W_RELEVANCE = 0.15
_W_AUTHORITY = 0.35
_W_AGREEMENT = 0.20
_W_COVERAGE = 0.30

# Band thresholds on the composite score.
HIGH_THRESHOLD = 0.70
MEDIUM_THRESHOLD = 0.45
LOW_THRESHOLD = 0.20

# A modest |logit| scale, so the squash is gentle and never acts as a hard gate.
_RELEVANCE_SCALE = 4.0

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by do does for from has have how in into is it its of on or "
    "our that the their them they this to we what when where which who why will with you "
    "your".split()
)


def _terms(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2}


def band_for(score: float) -> ConfidenceBand:
    if score >= HIGH_THRESHOLD:
        return ConfidenceBand.HIGH
    if score >= MEDIUM_THRESHOLD:
        return ConfidenceBand.MEDIUM
    if score >= LOW_THRESHOLD:
        return ConfidenceBand.LOW
    return ConfidenceBand.NONE


def _authority(cited: Sequence[CitedEvidence]) -> float:
    return max((SOURCE_AUTHORITY.get(c.source_type, _DEFAULT_AUTHORITY) for c in cited), default=0.0)


def _relevance(cited: Sequence[CitedEvidence]) -> float:
    best = max((c.rerank_score for c in cited), default=0.0)
    return 1.0 / (1.0 + math.exp(-best / _RELEVANCE_SCALE))


def _agreement(cited: Sequence[CitedEvidence]) -> float:
    # Count independent source *documents* (source_id, falling back to chunk_id).
    independent = {c.source_id or c.chunk_id for c in cited}
    if not independent:
        return 0.0
    return min(1.0, len(independent) / 2.0)


def _coverage(question: str, cited: Sequence[CitedEvidence]) -> float:
    q_terms = _terms(question)
    if not q_terms:
        return 1.0
    covered = _terms(" ".join(c.text for c in cited))
    return len(q_terms & covered) / len(q_terms)


def compute_confidence(
    question: str, cited: Sequence[CitedEvidence]
) -> tuple[float, dict[str, float], ConfidenceBand]:
    """Return ``(score, factors, band)``. With no cited evidence, confidence is 0."""
    if not cited:
        factors = {"relevance": 0.0, "authority": 0.0, "agreement": 0.0, "coverage": 0.0}
        return 0.0, factors, ConfidenceBand.NONE

    factors = {
        "relevance": round(_relevance(cited), 4),
        "authority": round(_authority(cited), 4),
        "agreement": round(_agreement(cited), 4),
        "coverage": round(_coverage(question, cited), 4),
    }
    score = (
        _W_RELEVANCE * factors["relevance"]
        + _W_AUTHORITY * factors["authority"]
        + _W_AGREEMENT * factors["agreement"]
        + _W_COVERAGE * factors["coverage"]
    )
    score = round(score, 4)
    return score, factors, band_for(score)
