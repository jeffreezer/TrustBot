"""Phase 4 answer generation: the fixed retrieve-then-answer pipeline."""
from __future__ import annotations

from .confidence import band_for, compute_confidence
from .generate import generate_answer, persist_answer
from .prompts import SYSTEM_INSTRUCTIONS, detect_injection
from .schema import (
    AnswerDraft,
    CitedEvidence,
    ConfidenceBand,
    EvidenceRef,
    GeneratedAnswer,
    Outcome,
)

__all__ = [
    "generate_answer",
    "persist_answer",
    "compute_confidence",
    "band_for",
    "detect_injection",
    "SYSTEM_INSTRUCTIONS",
    "AnswerDraft",
    "CitedEvidence",
    "ConfidenceBand",
    "EvidenceRef",
    "GeneratedAnswer",
    "Outcome",
]
