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
    SUPPORTED_YES = "supported_yes"
    SUPPORTED_NO = "supported_no"
    HAS_EXCEPTION = "has_exception"
    UNKNOWN = "unknown"


# Outcomes that assert an answer (vs. the unknown fallback). has_exception is a valid,
# accurate disclosure — not a problem state.
ANSWERED_OUTCOMES = frozenset(
    {Outcome.SUPPORTED_YES, Outcome.SUPPORTED_NO, Outcome.HAS_EXCEPTION}
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


class AnswerDraft(BaseModel):
    """Schema-enforced generator output. Unknown keys are ignored; a missing/invalid
    ``outcome`` fails validation and routes to the unknown-fallback."""

    model_config = ConfigDict(extra="ignore")

    outcome: Outcome
    short_answer: str = ""
    answer: str = ""
    claim: str = ""
    scope: str = ""
    exceptions: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    """A resolved, org-scoped citation persisted with the answer."""

    chunk_id: str
    source_type: str
    source_id: str | None = None
    title: str | None = None


class GeneratedAnswer(BaseModel):
    """The emitted, persisted answer. ``confidence`` is the composite score (NOT the
    rerank logit); ``confidence_factors`` records its components for transparency."""

    question: str
    outcome: Outcome
    short_answer: str = ""
    answer: str = ""
    claim: str = ""
    scope: str = ""
    exceptions: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    confidence_factors: dict[str, float] = Field(default_factory=dict)
    needs_human_review: bool = True
    review_reason: str | None = None
    freshness_status: str = "unknown"
    generated_by: str = ""
