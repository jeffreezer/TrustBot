"""Document quarantine — the review-mode injection-handling policy (Phase 8, layer 3).

When an ingested document screens as injection-like and the active policy is ``quarantine``
(review mode's default, Milestone 2), the document is excluded from the retrievable knowledge
base — its chunks are deleted so its content can never reach the model — and auto-processing
halts until an explicit human **release / mark-false-positive** action. The quarantine state
is persisted on the Evidence row (``status='quarantined'`` + ``injection_snippet``).

Respond mode's default policy is ``flag``: record the detection (``injection_flagged`` +
snippet) but keep the document retrievable — it is neutralized at answer time and the answer
is flagged for review. Both behaviors are built here so M2 can simply switch the policy on.

Audit is metadata-only: categories + counts, never the poisoned content (the short snippet is
shown in the UI, not dumped to server logs).
"""
from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db.models import AuditLog, Evidence, KnowledgeChunk
from .injection import InjectionFinding
from .policy import POLICY_QUARANTINE

STATUS_ACTIVE = "active"
STATUS_QUARANTINED = "quarantined"


def is_retrievable(evidence: Evidence) -> bool:
    """A document contributes to retrieval only while active (not quarantined/archived)."""
    return evidence.status == STATUS_ACTIVE


def flag_evidence(
    session: Session,
    evidence: Evidence,
    finding: InjectionFinding,
    *,
    actor: str = "system:ingest",
) -> None:
    """Respond-mode policy: record the detection but keep the document retrievable."""
    evidence.injection_flagged = True
    evidence.injection_snippet = (finding.snippet or "")[:512]
    session.add(
        AuditLog(
            org_id=evidence.org_id,
            actor=actor,
            action="evidence.injection_flag",
            target_type="evidence",
            target_id=evidence.id,
            payload={
                "categories": list(finding.categories),
                "from_obfuscation": finding.from_obfuscation,
                "extras": list(finding.extras),
            },
        )
    )


def quarantine_evidence(
    session: Session,
    evidence: Evidence,
    finding: InjectionFinding,
    *,
    actor: str = "system:ingest",
) -> int:
    """Review-mode policy: exclude a flagged document from the retrievable KB. Sets status
    quarantined, records the metadata-only snippet, DELETES its knowledge chunks (its content
    can no longer reach the model), and audits. Returns the number of chunks removed."""
    evidence.status = STATUS_QUARANTINED
    evidence.injection_flagged = True
    evidence.injection_snippet = (finding.snippet or "")[:512]
    result = session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.org_id == evidence.org_id,
            KnowledgeChunk.source_id == evidence.id,
        )
    )
    removed = int(result.rowcount or 0)
    session.add(
        AuditLog(
            org_id=evidence.org_id,
            actor=actor,
            action="evidence.quarantine",
            target_type="evidence",
            target_id=evidence.id,
            payload={
                "categories": list(finding.categories),
                "from_obfuscation": finding.from_obfuscation,
                "extras": list(finding.extras),
                "chunks_removed": removed,
            },
        )
    )
    return removed


def release_evidence(
    session: Session,
    evidence: Evidence,
    *,
    actor: str,
    false_positive: bool = False,
) -> None:
    """Human release / mark-false-positive: clear quarantine so the document can be re-ingested
    (the caller re-runs ingestion to repopulate chunks). ``false_positive`` additionally clears
    the injection flag/snippet. Audited."""
    evidence.status = STATUS_ACTIVE
    if false_positive:
        evidence.injection_flagged = False
        evidence.injection_snippet = None
    session.add(
        AuditLog(
            org_id=evidence.org_id,
            actor=actor,
            action="evidence.release",
            target_type="evidence",
            target_id=evidence.id,
            payload={"false_positive": false_positive},
        )
    )


def apply_ingestion_policy(
    session: Session,
    evidence: Evidence,
    finding: InjectionFinding,
    policy: str,
    *,
    actor: str = "system:ingest",
) -> str:
    """Apply the per-mode policy to a detection at ingestion. Returns ``"quarantined"`` (the
    caller must NOT create/keep chunks) or ``"flagged"`` (chunks remain, neutralized at answer
    time)."""
    if policy == POLICY_QUARANTINE:
        quarantine_evidence(session, evidence, finding, actor=actor)
        return "quarantined"
    flag_evidence(session, evidence, finding, actor=actor)
    return "flagged"


__all__ = [
    "STATUS_ACTIVE",
    "STATUS_QUARANTINED",
    "is_retrievable",
    "flag_evidence",
    "quarantine_evidence",
    "release_evidence",
    "apply_ingestion_policy",
]
