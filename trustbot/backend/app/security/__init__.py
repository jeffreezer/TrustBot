"""Security hardening (Phase 8): prompt-injection detection, neutralization, quarantine."""
from __future__ import annotations

from .injection import (
    REDACTION_MARKER,
    InjectionFinding,
    detect_injection,
    has_substance,
    neutralize,
    normalize_text,
    screen,
    screen_filename,
)
from .policy import (
    POLICY_FLAG_NEUTRALIZE,
    POLICY_QUARANTINE,
    policy_for_mode,
)

__all__ = [
    "InjectionFinding",
    "REDACTION_MARKER",
    "detect_injection",
    "has_substance",
    "neutralize",
    "normalize_text",
    "screen",
    "screen_filename",
    "POLICY_FLAG_NEUTRALIZE",
    "POLICY_QUARANTINE",
    "policy_for_mode",
]
