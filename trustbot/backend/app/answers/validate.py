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

from .schema import (
    RESPOND_DRAFTED,
    AnswerDraft,
    CitedEvidence,
    Claim,
    ClaimStatus,
    ClaimType,
    RespondOutcome,
)

# Document-tier basis: a current owned policy / control / attestation document. This is the
# *higher-authority* tier — an answer with one of these stands on its own.
CONTROLLING_SOURCE_TYPES = frozenset({"policy", "control", "evidence"})

# Acceptable basis for an affirmative (05, reuse rule): a document-tier source OR a resolved
# prior approved answer. Real questionnaires include analyst-written narrative attestations
# approved with no underlying document — those must be reusable. A reused approval is a
# lower-authority tier (re-validated, always human-reviewed), but it IS a valid basis. The
# model's own ungrounded assertion never counts; marketing copy (company_profile) never
# counts on its own.
ACCEPTABLE_BASIS_SOURCE_TYPES = CONTROLLING_SOURCE_TYPES | frozenset({"approved_answer"})

_AFFIRMATIVE = frozenset({RespondOutcome.ATTESTED, RespondOutcome.QUALIFIED})

# Canonical certification names + their recognizers. Two uses: (1) ``asserted_certifications``
# scans emitted prose as a defense-in-depth backstop (the eval no_overclaim gate); (2)
# ``normalize_cert`` maps a claim's free-text ``subject`` ("FedRAMP", "SOC2", "ISO/IEC 27001")
# onto a canonical name so it can be compared against the org's held attestations.
_CERT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsoc\s*2\b", "soc 2"),
    (r"\bsoc\s*1\b", "soc 1"),
    (r"\biso\s*/?\s*(?:iec\s*)?27001\b", "iso 27001"),
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

def acceptable_basis_gate(draft: AnswerDraft, cited: Sequence[CitedEvidence]) -> str | None:
    """Anti-fabrication (05, reuse rule): an attested/qualified answer must cite ≥1 acceptable
    basis — a policy/control/attestation OR a prior approved answer. The model's own
    ungrounded assertion (or marketing-only) never counts. Default deny → needs_input.

    (The pipeline additionally resolves an approved-answer basis server-side, so a
    model-claimed approval that doesn't resolve to a real record is rejected too.)"""
    if draft.outcome not in _AFFIRMATIVE:
        return None
    if any(c.source_type in ACCEPTABLE_BASIS_SOURCE_TYPES for c in cited):
        return None
    return (
        "affirmative answer cites no acceptable basis (policy / control / attestation, or a "
        "prior approved answer)"
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


def normalize_cert(subject: str) -> str:
    """Map a claim's free-text certification ``subject`` onto a canonical cert name (so
    "FedRAMP" / "SOC2" / "ISO/IEC 27001" compare against the org's held attestations). Falls
    back to a lowercased/whitespace-collapsed form when no canonical name matches."""
    low = (subject or "").lower()
    for pattern, name in _CERT_PATTERNS:
        if re.search(pattern, low):
            return name
    return re.sub(r"\s+", " ", low).strip()


def certification_claims(claims: Sequence[Claim]) -> list[Claim]:
    return [c for c in claims if c.claim_type == ClaimType.CERTIFICATION]


def validate_certification_claims(
    claims: Sequence[Claim], available_certs: Sequence[str]
) -> list[str]:
    """Certification overclaim, read from the STRUCTURE not the prose (07 §3.3).

    A ``certification`` claim with ``status: affirmed`` must rest on an attestation the org
    actually holds (``available_certs``, derived server-side from the org's attestation
    evidence). A ``denied`` / ``qualified`` / ``unknown`` certification is **never** flagged —
    so a grounded negative ("No, not FedRAMP authorized") no longer trips this check. The pass
    is **per-claim**, so a mixed answer ("SOC 2 certified, not FedRAMP") flags only the
    unsupported affirmation, never the truthful denial. This replaces the old polarity-blind
    prose-keyword scan that mis-fired on correct negatives."""
    available = {normalize_cert(c) for c in available_certs}
    overclaimed = sorted(
        c.subject
        for c in certification_claims(claims)
        if c.status == ClaimStatus.AFFIRMED and normalize_cert(c.subject) not in available
    )
    if overclaimed:
        return [f"certification affirmed without a supporting attestation: {overclaimed}"]
    return []


def derive_cert_outcome(
    cert_claims: Sequence[Claim], available_certs: Sequence[str]
) -> RespondOutcome | None:
    """Derive a certification question's outcome from the declared claim status (07 §3.2),
    polarity-first so the prose classifier can never read a denial as a "yes".

    Returns ``None`` when there are no certification claims (the caller keeps the prose-derived
    outcome — Phase 1 derives from claims for cert questions only). Otherwise:
      - an ``affirmed`` cert without a held attestation → ``needs_input`` (overclaim, fail-closed)
      - any ``qualified`` cert, or a mix of supported affirmations and denials → ``qualified``
      - all ``affirmed`` (each with a held attestation) → ``attested``
      - a ``denied`` cert **with** a resolvable basis → ``negative`` (a grounded, clean "no");
        a denial with no basis, or nothing actionable → ``needs_input``"""
    cert_claims = certification_claims(cert_claims)
    if not cert_claims:
        return None
    available = {normalize_cert(c) for c in available_certs}

    def has_attestation(claim: Claim) -> bool:
        return normalize_cert(claim.subject) in available

    affirmed = [c for c in cert_claims if c.status == ClaimStatus.AFFIRMED]
    qualified = [c for c in cert_claims if c.status == ClaimStatus.QUALIFIED]
    denied = [c for c in cert_claims if c.status == ClaimStatus.DENIED]

    if any(not has_attestation(c) for c in affirmed):
        return RespondOutcome.NEEDS_INPUT  # overclaim — don't emit a false "yes"
    if qualified or (affirmed and denied):
        return RespondOutcome.QUALIFIED
    if affirmed:
        return RespondOutcome.ATTESTED
    if denied:
        return (
            RespondOutcome.NEGATIVE
            if any(c.basis for c in denied)
            else RespondOutcome.NEEDS_INPUT
        )
    return RespondOutcome.NEEDS_INPUT


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


# System-prompt / internal-instruction phrases that must never appear in a customer-facing
# answer (Phase 8, layer 4). An injection that tries to make the model echo its instructions
# or leak the redaction marker is caught here as an output check.
_LEAKAGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"you are trustbot", re.IGNORECASE),
    re.compile(r"system prompt|system instructions?", re.IGNORECASE),
    re.compile(r"these (?:are )?(?:my|the) instructions", re.IGNORECASE),
    re.compile(r"⟦redacted-injection⟧"),  # the neutralization marker must not surface
    re.compile(r"\bRULES:\B|ANSWER ONLY from the EVIDENCE", re.IGNORECASE),
)


def validate_no_system_leakage(draft: AnswerDraft) -> list[str]:
    """The answer must not echo system-prompt / internal-instruction content (Phase 8, layer
    4): an injection that tries to exfiltrate or parrot the system instructions is caught as
    an output check, complementing the shareability check on cited evidence."""
    if draft.outcome not in RESPOND_DRAFTED:
        return []
    text = f"{draft.short_answer}\n{draft.answer}\n{draft.claim}\n{draft.scope}"
    if any(p.search(text) for p in _LEAKAGE_PATTERNS):
        return ["answer contains system-prompt / internal-instruction content (possible leakage)"]
    return []


def run_review_checks(
    draft: AnswerDraft,
    cited: Sequence[CitedEvidence],
    *,
    grounding_refs: Sequence[str],
    claims: Sequence[Claim],
    available_certs: Sequence[str],
    customer_facing: bool = True,
) -> list[str]:
    """The review-flag validators (aggregated reasons; empty == pass). The certification check
    reads the structured ``claims`` (07 §3.3), not the prose — polarity-aware and per-claim."""
    reasons: list[str] = []
    reasons += validate_required_fields(draft)
    reasons += validate_citations(draft, grounding_refs)
    reasons += validate_certification_claims(claims, available_certs)
    reasons += validate_shareability(cited, customer_facing=customer_facing)
    reasons += validate_no_system_leakage(draft)
    return reasons


__all__ = [
    "CONTROLLING_SOURCE_TYPES",
    "ACCEPTABLE_BASIS_SOURCE_TYPES",
    "FindingStatus",
    "asserted_certifications",
    "normalize_cert",
    "certification_claims",
    "acceptable_basis_gate",
    "open_findings_gate",
    "validate_required_fields",
    "validate_citations",
    "validate_certification_claims",
    "derive_cert_outcome",
    "validate_shareability",
    "validate_no_system_leakage",
    "run_review_checks",
]
