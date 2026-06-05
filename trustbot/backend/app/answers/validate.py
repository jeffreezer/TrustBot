"""Deterministic answer validators — run before persist/return, fail closed.

None of these trust the model. Each returns a list of human-readable failure reasons
(empty == pass); any non-empty result routes the answer to human review. They are pure
functions over already-loaded data (no DB), so they unit-test without a database; the
pipeline supplies the org-scoped inputs (the resolved citations, the set of
certifications the org actually has attestation evidence for).
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from .schema import ANSWERED_OUTCOMES, AnswerDraft, CitedEvidence, Outcome

# Certifications we can recognize in answer text, mapped to a normalized name. The
# pipeline supplies which of these the org actually has attestation evidence for; any
# *asserted* cert not in that set is an overclaim.
_CERT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsoc\s*2\b", "soc 2"),
    (r"\bsoc\s*1\b", "soc 1"),
    (r"\biso\s*27001\b", "iso 27001"),
    (r"\bpci(?:\s*dss)?\b", "pci dss"),
    (r"\bfedramp\b", "fedramp"),
    (r"\bhipaa\b", "hipaa"),
    (r"\bfips\s*140\b", "fips 140"),
)


def asserted_certifications(text: str) -> set[str]:
    low = (text or "").lower()
    return {name for pattern, name in _CERT_PATTERNS if re.search(pattern, low)}


def validate_required_fields(draft: AnswerDraft) -> list[str]:
    """Answered outcomes must carry a claim and a short answer."""
    reasons: list[str] = []
    if draft.outcome in ANSWERED_OUTCOMES:
        if not draft.short_answer.strip():
            reasons.append("missing short_answer for an answered outcome")
        if not draft.claim.strip():
            reasons.append("missing claim for an answered outcome")
    return reasons


def validate_citations(draft: AnswerDraft, grounding_refs: Sequence[str]) -> list[str]:
    """Every cited ref must be one of the org-scoped grounding refs; answered outcomes
    must cite at least one. Catches hallucinated or out-of-scope citations."""
    reasons: list[str] = []
    allowed = set(grounding_refs)
    unknown = [r for r in draft.evidence_refs if r not in allowed]
    if unknown:
        reasons.append(f"cited evidence not in retrieved grounding: {sorted(unknown)}")
    if draft.outcome in ANSWERED_OUTCOMES and not draft.evidence_refs:
        reasons.append("answered outcome with no cited evidence")
    return reasons


def validate_certifications(
    draft: AnswerDraft, available_certs: Sequence[str]
) -> list[str]:
    """No certification asserted unless the org has a supporting attestation record."""
    if draft.outcome not in ANSWERED_OUTCOMES:
        return []
    available = {c.lower() for c in available_certs}
    text = f"{draft.short_answer}\n{draft.answer}\n{draft.claim}"
    asserted = asserted_certifications(text)
    unsupported = sorted(c for c in asserted if c not in available)
    if unsupported:
        return [f"certification claimed without supporting evidence: {unsupported}"]
    return []


def validate_shareability(
    cited: Sequence[CitedEvidence], *, customer_facing: bool = True
) -> list[str]:
    """No internal-only / non-customer-shareable content in a customer-facing answer
    (the same gate Phase 3 retrieval applies)."""
    if not customer_facing:
        return []
    leaked = sorted(
        {c.title or c.chunk_id for c in cited if not c.customer_shareable}
    )
    if leaked:
        return [f"internal-only evidence cited in a customer-facing answer: {leaked}"]
    return []


def run_all(
    draft: AnswerDraft,
    cited: Sequence[CitedEvidence],
    *,
    grounding_refs: Sequence[str],
    available_certs: Sequence[str],
    customer_facing: bool = True,
) -> list[str]:
    """All validators; aggregated failure reasons (empty == pass)."""
    reasons: list[str] = []
    reasons += validate_required_fields(draft)
    reasons += validate_citations(draft, grounding_refs)
    reasons += validate_certifications(draft, available_certs)
    reasons += validate_shareability(cited, customer_facing=customer_facing)
    return reasons


# Re-exported for the pipeline's convenience.
__all__ = [
    "Outcome",
    "asserted_certifications",
    "validate_required_fields",
    "validate_citations",
    "validate_certifications",
    "validate_shareability",
    "run_all",
]
