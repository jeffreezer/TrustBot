"""Deterministic respond-mode validators — run before persist, fail closed (05 §5/§9).

Two of these are **downgrade gates**: an attested/qualified answer that cites no controlling
owned control/policy/attestation, or a provided report with an open finding lacking a target
date, cannot auto-draft and must fall to ``needs_input``. The rest are **review flags** (cert
overclaim, hallucinated citation, internal-only leak) — they set ``needs_human_review`` but
keep the answer. All are pure functions over already-loaded, org-scoped data (no DB).
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .schema import RESPOND_DRAFTED, AnswerDraft, CitedEvidence, RespondOutcome

# Source types that substantiate an attested/qualified claim. A reused prior answer
# (approved_answer) or marketing facts (company_profile) do NOT, on their own, control.
CONTROLLING_SOURCE_TYPES = frozenset({"policy", "control", "evidence"})

_AFFIRMATIVE = frozenset({RespondOutcome.ATTESTED, RespondOutcome.QUALIFIED})

# Certifications recognizable in answer text; the pipeline supplies which the org actually
# holds attestation evidence for — any *asserted* cert not in that set is an overclaim.
_CERT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsoc\s*2\b", "soc 2"),
    (r"\bsoc\s*1\b", "soc 1"),
    (r"\biso\s*27001\b", "iso 27001"),
    (r"\bpci(?:\s*dss)?\b", "pci dss"),
    (r"\bfedramp\b", "fedramp"),
    (r"\bhipaa\b", "hipaa"),
    (r"\bfips\s*140\b", "fips 140"),
)


@dataclass(frozen=True)
class FindingStatus:
    """The fields the open-finding gate needs (DB-free, so it unit-tests without a DB)."""

    finding_id: str
    external_ref: str | None
    status: str
    has_target_date: bool


def asserted_certifications(text: str) -> set[str]:
    low = (text or "").lower()
    return {name for pattern, name in _CERT_PATTERNS if re.search(pattern, low)}


# --- downgrade gates (failure => needs_input) -------------------------------

def controlling_gate(draft: AnswerDraft, cited: Sequence[CitedEvidence]) -> str | None:
    """Anti-fabrication, reframed (05 §5): an attested/qualified answer must cite ≥1
    controlling policy/control/attestation owned by the org. Default deny → needs_input."""
    if draft.outcome not in _AFFIRMATIVE:
        return None
    if any(c.source_type in CONTROLLING_SOURCE_TYPES for c in cited):
        return None
    return (
        "affirmative answer cites no controlling policy / control / attestation owned by "
        "the organization"
    )


def open_findings_gate(
    remediation_required: bool, findings: Sequence[FindingStatus]
) -> str | None:
    """A provided report with an open/in_progress finding that has no target remediation
    date cannot auto-draft (05 §9, Domain Rule 4) → needs_input."""
    if not remediation_required:
        return None
    missing = sorted(
        f.external_ref or f.finding_id
        for f in findings
        if f.status in ("open", "in_progress") and not f.has_target_date
    )
    if missing:
        return (
            f"provided report has open finding(s) without a target remediation date: {missing}"
        )
    return None


# --- review flags (failure => needs_human_review, answer kept) --------------

def validate_required_fields(draft: AnswerDraft) -> list[str]:
    reasons: list[str] = []
    if draft.outcome in RESPOND_DRAFTED:
        if not draft.short_answer.strip():
            reasons.append("missing short_answer for a drafted outcome")
        if not draft.claim.strip():
            reasons.append("missing claim for a drafted outcome")
    return reasons


def validate_citations(draft: AnswerDraft, grounding_refs: Sequence[str]) -> list[str]:
    """Every cited ref must be one of the org-scoped grounding refs; an affirmative answer
    must cite at least one. Catches hallucinated/out-of-scope citations."""
    reasons: list[str] = []
    allowed = set(grounding_refs)
    unknown = [r for r in draft.evidence_refs if r not in allowed]
    if unknown:
        reasons.append(f"cited evidence not in retrieved grounding: {sorted(unknown)}")
    if draft.outcome in _AFFIRMATIVE and not draft.evidence_refs:
        reasons.append("affirmative answer with no cited evidence")
    return reasons


def validate_certifications(
    draft: AnswerDraft, available_certs: Sequence[str]
) -> list[str]:
    """No certification asserted unless the org has a supporting attestation record."""
    if draft.outcome not in RESPOND_DRAFTED:
        return []
    available = {c.lower() for c in available_certs}
    text = f"{draft.short_answer}\n{draft.answer}\n{draft.claim}"
    unsupported = sorted(c for c in asserted_certifications(text) if c not in available)
    if unsupported:
        return [f"certification claimed without supporting evidence: {unsupported}"]
    return []


def validate_shareability(
    cited: Sequence[CitedEvidence], *, customer_facing: bool = True
) -> list[str]:
    """No internal-only / non-customer-shareable content in a customer-facing answer."""
    if not customer_facing:
        return []
    leaked = sorted({c.title or c.chunk_id for c in cited if not c.customer_shareable})
    if leaked:
        return [f"internal-only evidence cited in a customer-facing answer: {leaked}"]
    return []


def run_review_checks(
    draft: AnswerDraft,
    cited: Sequence[CitedEvidence],
    *,
    grounding_refs: Sequence[str],
    available_certs: Sequence[str],
    customer_facing: bool = True,
) -> list[str]:
    """The review-flag validators (aggregated reasons; empty == pass)."""
    reasons: list[str] = []
    reasons += validate_required_fields(draft)
    reasons += validate_citations(draft, grounding_refs)
    reasons += validate_certifications(draft, available_certs)
    reasons += validate_shareability(cited, customer_facing=customer_facing)
    return reasons


__all__ = [
    "CONTROLLING_SOURCE_TYPES",
    "FindingStatus",
    "asserted_certifications",
    "controlling_gate",
    "open_findings_gate",
    "validate_required_fields",
    "validate_citations",
    "validate_certifications",
    "validate_shareability",
    "run_review_checks",
]
