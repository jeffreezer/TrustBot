"""Schemas for Phase 4 answer generation.

Two Pydantic models bound the trust boundary:

- ``AnswerDraft`` is what the *generator* returns (schema-enforced; an invalid draft
  is rejected and routed to the unknown-fallback — the model is never trusted blindly).
- ``GeneratedAnswer`` is what TrustBot *emits and persists* after deterministic
  confidence scoring and validation.

``CitedEvidence`` is a plain dataclass (no DB) so the confidence model and the
validators can be unit-tested without a database.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Outcome(str, Enum):
    """**Review mode (Milestone 2)** taxonomy — parked. The respond-mode pipeline does not
    use these; kept so the vendor-review posture can fork onto them later (05 §2)."""

    SUPPORTED_YES = "supported_yes"
    SUPPORTED_NO = "supported_no"
    HAS_EXCEPTION = "has_exception"
    UNKNOWN = "unknown"


# Review-mode answered outcomes (parked).
ANSWERED_OUTCOMES = frozenset(
    {Outcome.SUPPORTED_YES, Outcome.SUPPORTED_NO, Outcome.HAS_EXCEPTION}
)


class RespondOutcome(str, Enum):
    """**Respond mode (Milestone 1)** taxonomy — the active posture (05 §5). The vendor puts
    its best honest foot forward; ``has_exception`` is intentionally absent (a SOC 2 exception
    never changes the outcome — the report self-contains it)."""

    ATTESTED = "attested"        # a control/policy/attestation backs an affirmative answer
    QUALIFIED = "qualified"      # affirmative with a vendor-stated scope (not an auditor finding)
    NEGATIVE = "negative"        # an honest "no"
    NEEDS_INPUT = "needs_input"  # no controlling evidence / needs human judgment — no draft


# Respond-mode outcomes that produce a draft; ``needs_input`` does not.
RESPOND_DRAFTED = frozenset(
    {RespondOutcome.ATTESTED, RespondOutcome.QUALIFIED, RespondOutcome.NEGATIVE}
)


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True)
class CitedEvidence:
    """A retrieved chunk available for citation — the DB-free view used by the
    confidence model and validators."""

    chunk_id: str
    source_type: str
    source_id: str | None
    title: str
    text: str
    customer_shareable: bool
    confidentiality: str
    rerank_score: float
    fusion_score: float


class ProvidedDocument(BaseModel):
    """A document the answer provides — referenced by id only; the bytes are served by the
    org-scoped, audited download endpoint (05 §8), never a bearer link."""

    document_id: str
    title: str | None = None


class CandidateDocument(BaseModel):
    """A selectable document offered to the analyst for a generic document-request (05 §8.5):
    org-scoped, customer_shareable evidence, relevance-ranked, labeled by kind + title.
    Providing a document is a disclosure decision — the system surfaces candidates and the
    human chooses; nothing is attached automatically. ``recommended`` marks the governing
    document the answer cited, pre-selected so the common case is a one-click confirm."""

    document_id: str
    title: str | None = None
    document_kind: str | None = None
    recommended: bool = False


class AnswerDraft(BaseModel):
    """Schema-enforced generator output. Unknown keys are ignored; a missing/invalid
    ``outcome`` fails validation and routes to the needs-input fallback. ``requires_document``
    is the question-type classification (document-request vs attestation, 05 §7); the
    pipeline — not the model — resolves which org-scoped documents/findings are referenced."""

    model_config = ConfigDict(extra="ignore")

    outcome: RespondOutcome
    short_answer: str = ""
    answer: str = ""
    claim: str = ""
    scope: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    requires_document: bool = False
    model_note: str = ""  # reason carried when outcome is needs_input


class EvidenceRef(BaseModel):
    """A resolved, org-scoped citation persisted with the answer."""

    chunk_id: str
    source_type: str
    source_id: str | None = None
    title: str | None = None


class SubAnswer(BaseModel):
    """One atomic part of a decomposed compound answer (06): its own sub-question, outcome,
    text, and citations, so the reviewer sees which evidence supports which part — and an
    unsupported part is flagged, never silently dropped."""

    sub_question: str
    outcome: RespondOutcome
    short_answer: str = ""
    answer: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    needs_human_review: bool = True
    review_reason: str | None = None


class GeneratedAnswer(BaseModel):
    """The emitted, persisted answer. ``confidence`` is the composite score (NOT the rerank
    logit). Respond-mode attributes (05 §5): ``requires_document`` + ``provided_documents``
    for document-request answers; ``remediation_required`` + ``finding_refs`` when a provided
    document carries findings (rendered from the register)."""

    question: str
    outcome: RespondOutcome
    short_answer: str = ""
    answer: str = ""
    claim: str = ""
    scope: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    requires_document: bool = False
    provided_documents: list[ProvidedDocument] = Field(default_factory=list)
    # Generic document-request (05 §8): no specific artifact named, so attachment is deferred
    # to a human. The answer text is still drafted; these surface the picker.
    document_selection_required: bool = False
    candidate_documents: list[CandidateDocument] = Field(default_factory=list)
    remediation_required: bool = False
    finding_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    confidence_factors: dict[str, float] = Field(default_factory=dict)
    needs_human_review: bool = True
    review_reason: str | None = None
    freshness_status: str = "unknown"
    generated_by: str = ""
    # Phase 8: injection-like content was detected (in the question or cited evidence),
    # neutralized, and flagged for human review. The answer is still produced; nothing acted on.
    injection_flagged: bool = False
    # Adaptive retrieval loop (06): which path gathered the evidence ("fixed" | "loop" |
    # "decomposed") and the ordered, metadata-only tool-call trail (audited; empty on the
    # fixed path). ``sub_answers`` holds the per-part breakdown for a decomposed answer.
    retrieval_path: str = "fixed"
    tool_calls: list[dict] = Field(default_factory=list)
    sub_answers: list[SubAnswer] = Field(default_factory=list)
