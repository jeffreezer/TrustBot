"""Per-posture injection-handling policy (Phase 8, layer 3).

On detection the handling forks by posture (build-guide Phase 8 decision):

- **respond mode** (Milestone 1, active) → ``flag_neutralize``: the content is already inert
  as fenced data, so we never execute it; we neutralize it (strip obfuscation, redact the
  directive) so the live string can't reach the model, surface the snippet, flag the item for
  human review, and STILL produce a grounded answer (or ``needs_input`` if honest). Nothing is
  blocked; the audit signal is recorded.
- **review mode** (Milestone 2) → ``quarantine``: a flagged document is excluded from the
  retrievable knowledge base (its content can't reach the model at all) and auto-processing
  halts until an explicit human release / mark-false-positive action.

Both behaviors are built now; the policy is a per-mode setting so respond uses flag-neutralize
and review uses quarantine (M2 turns review on).
"""
from __future__ import annotations

from ..config import settings

POLICY_FLAG_NEUTRALIZE = "flag_neutralize"
POLICY_QUARANTINE = "quarantine"
VALID_POLICIES = frozenset({POLICY_FLAG_NEUTRALIZE, POLICY_QUARANTINE})


def policy_for_mode(mode: str) -> str:
    """Resolve the injection-handling policy for an answer/ingestion posture.

    Defaults: respond → flag_neutralize, review → quarantine. Both come from settings so an
    operator can override per posture without code changes."""
    normalized = (mode or "respond").strip().lower()
    if normalized == "review":
        return settings.injection_policy_review
    return settings.injection_policy_respond
