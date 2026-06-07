"""Answer generation: the fixed retrieve-then-answer pipeline (respond mode, M1)."""
from __future__ import annotations

from .confidence import band_for, compute_confidence
from .generate import generate_answer, persist_answer
from .prompts import SYSTEM_INSTRUCTIONS, detect_injection, respond_system_instructions
from .schema import (
    RESPOND_DRAFTED,
    AnswerDraft,
    CitedEvidence,
    ConfidenceBand,
    EvidenceRef,
    GeneratedAnswer,
    Outcome,
    ProvidedDocument,
    RespondOutcome,
)

__all__ = [
    "generate_answer",
    "persist_answer",
    "compute_confidence",
    "band_for",
    "detect_injection",
    "SYSTEM_INSTRUCTIONS",
    "respond_system_instructions",
    "AnswerDraft",
    "CitedEvidence",
    "ConfidenceBand",
    "EvidenceRef",
    "GeneratedAnswer",
    "ProvidedDocument",
    "Outcome",
    "RespondOutcome",
    "RESPOND_DRAFTED",
]
