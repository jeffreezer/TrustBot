"""Fixed retrieve-then-answer pipeline (Phase 4 generation half).

Flow, deliberately fixed (CLAUDE.md principle 6 — no agentic loop / decomposition yet):

    retrieve (org-scoped, customer-shareable) → draft (generator) → resolve citations →
    composite confidence → deterministic validators → GeneratedAnswer

Every branch fails closed. Missing/insufficient/low-confidence/conflicting evidence, a
malformed draft, a failed validator, an injection-like chunk, or an un-corroborated
reused answer all route to ``needs_human_review`` with a reason — never a confident
guess (principle 1). Drafts are never auto-emitted; a human approves in Phase 5.
"""
from __future__ import annotations

import json
import uuid
from datetime import date

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Answer,
    AuditLog,
    Control,
    Evidence,
    Organization,
    Question,
    Questionnaire,
)
from ..providers import (
    DraftRequest,
    GenerationProvider,
    GroundingDoc,
    get_generation_provider,
)
from ..retrieval import RetrievalFilters, RetrievedChunk, retrieve
from .confidence import compute_confidence
from .prompts import SYSTEM_INSTRUCTIONS, detect_injection
from .schema import (
    ANSWERED_OUTCOMES,
    AnswerDraft,
    CitedEvidence,
    ConfidenceBand,
    EvidenceRef,
    GeneratedAnswer,
    Outcome,
)
from .validate import run_all

# evidence_type → certification the org can therefore claim (attestation records).
_ATTESTATION_CERTS = {
    "soc2_report": "soc 2",
    "iso_certificate": "iso 27001",
    "pci_aoc": "pci dss",
}
_AD_HOC_QUESTIONNAIRE = "Ad-hoc questions (API)"


def _grounding_from_retrieved(
    retrieved: list[RetrievedChunk],
) -> tuple[list[CitedEvidence], list[GroundingDoc]]:
    cited: list[CitedEvidence] = []
    docs: list[GroundingDoc] = []
    for rc in retrieved:
        meta = rc.meta or {}
        title = meta.get("title") or meta.get("control_code") or rc.source_type
        shareable = bool(meta.get("customer_shareable", False))
        ref = str(rc.chunk_id)
        cited.append(
            CitedEvidence(
                chunk_id=ref,
                source_type=rc.source_type,
                source_id=str(rc.source_id) if rc.source_id else None,
                title=title,
                text=rc.chunk_text,
                customer_shareable=shareable,
                confidentiality=meta.get("confidentiality", "internal"),
                rerank_score=rc.rerank_score,
                fusion_score=rc.fusion_score,
            )
        )
        docs.append(
            GroundingDoc(
                ref=ref,
                source_type=rc.source_type,
                title=str(title),
                text=rc.chunk_text,
                customer_shareable=shareable,
            )
        )
    return cited, docs


def _available_certs(session: Session, org_id: uuid.UUID) -> set[str]:
    types = session.scalars(
        select(Evidence.evidence_type)
        .where(Evidence.org_id == org_id)
        .where(Evidence.evidence_type.in_(_ATTESTATION_CERTS.keys()))
        .distinct()
    ).all()
    return {_ATTESTATION_CERTS[t] for t in types if t in _ATTESTATION_CERTS}


def _freshness(session: Session, org_id: uuid.UUID, cited: list[CitedEvidence]) -> str:
    """Derive a freshness label from the cited sources' validity / review dates."""
    source_ids = {
        uuid.UUID(c.source_id)
        for c in cited
        if c.source_id and c.source_type in {"evidence", "policy", "control"}
    }
    if not source_ids:
        return "unknown"
    today = date.today()
    statuses: set[str] = set()
    evidence = session.scalars(
        select(Evidence).where(Evidence.org_id == org_id, Evidence.id.in_(source_ids))
    ).all()
    for ev in evidence:
        if ev.valid_until and ev.valid_until < today:
            statuses.add("stale")
        else:
            statuses.add("current")
    controls = session.scalars(
        select(Control).where(Control.org_id == org_id, Control.id.in_(source_ids))
    ).all()
    for ctrl in controls:
        if ctrl.next_review and ctrl.next_review < today:
            statuses.add("review_due")
        else:
            statuses.add("current")
    if "stale" in statuses:
        return "stale"
    if "review_due" in statuses:
        return "review_due"
    return "current" if statuses else "unknown"


def _unknown_answer(
    question: str, reason: str, generated_by: str
) -> GeneratedAnswer:
    return GeneratedAnswer(
        question=question,
        outcome=Outcome.UNKNOWN,
        confidence=0.0,
        confidence_band=ConfidenceBand.NONE,
        confidence_factors={"relevance": 0.0, "authority": 0.0, "agreement": 0.0, "coverage": 0.0},
        needs_human_review=True,
        review_reason=reason,
        freshness_status="unknown",
        generated_by=generated_by,
    )


def _normalize_ref(ref: str) -> str:
    """Strip a model-echoed ``[ref:<id>]`` / ``ref:<id>`` / ``[<id>]`` wrapper down to the
    bare chunk id, so a citation resolves regardless of how the model formatted it."""
    r = ref.strip().strip("[](){}").strip()
    if r.lower().startswith("ref:"):
        r = r[4:]
    return r.strip().strip("[](){}").strip()


def generate_answer(
    session: Session,
    *,
    org: Organization,
    question: str,
    top_k: int | None = None,
    generator: GenerationProvider | None = None,
) -> GeneratedAnswer:
    """Draft and validate one evidence-grounded answer (or an unknown fallback)."""
    question = question.strip()
    generator = generator or get_generation_provider()
    generated_by = f"phase4:{generator.name}"
    if not question:
        return _unknown_answer(question, "Empty question.", generated_by)

    # The question is untrusted inbound text. If it looks like it's trying to inject
    # instructions, flag it for a human rather than answering it (CLAUDE.md: treat such
    # content as data, never act on it).
    if detect_injection(question):
        return _unknown_answer(
            question,
            "Question contains injection-like content; flagged for human review.",
            generated_by,
        )

    # Customer-facing answer: retrieve only customer-shareable evidence (the Phase 3
    # gate), so internal-only material can never enter the grounding in the first place.
    filters = RetrievalFilters(org_id=org.id, customer_shareable=True)
    retrieved = retrieve(session, query=question, filters=filters, top_k=top_k)
    if not retrieved:
        return _unknown_answer(
            question,
            "No customer-shareable evidence was retrieved for this question.",
            generated_by,
        )

    cited_all, grounding = _grounding_from_retrieved(retrieved)
    grounding_refs = [d.ref for d in grounding]
    injection_refs = {c.chunk_id for c in cited_all if detect_injection(c.text)}

    raw = generator.draft(
        DraftRequest(
            question=question,
            instructions=SYSTEM_INSTRUCTIONS,
            grounding=tuple(grounding),
        )
    )
    try:
        draft = AnswerDraft.model_validate_json(raw)
    except ValidationError:
        return _unknown_answer(
            question, "Generator returned a malformed or schema-invalid draft.", generated_by
        )

    if draft.outcome == Outcome.UNKNOWN:
        note = ""
        try:
            note = (json.loads(raw) or {}).get("model_note", "")
        except (ValueError, TypeError):
            note = ""
        return _unknown_answer(
            question, note or "Generator could not answer from the retrieved evidence.",
            generated_by,
        )

    # Normalize cited refs before resolving/validating: models often echo the prompt's
    # "[ref:<id>]" label, returning "ref:<id>" or "[<id>]" instead of the bare chunk id.
    draft.evidence_refs = [r for r in (_normalize_ref(x) for x in draft.evidence_refs) if r]

    # Resolve citations to the actual retrieved chunks (org-scoped by construction).
    by_ref = {c.chunk_id: c for c in cited_all}
    cited = [by_ref[r] for r in draft.evidence_refs if r in by_ref]
    if not cited:
        return _unknown_answer(
            question,
            "Draft cited no resolvable evidence from the retrieved grounding.",
            generated_by,
        )

    score, factors, band = compute_confidence(question, cited)
    available_certs = _available_certs(session, org.id)
    reasons = run_all(
        draft,
        cited,
        grounding_refs=grounding_refs,
        available_certs=available_certs,
        customer_facing=True,
    )

    # Approved-answer reuse is a candidate, not a bypass (principle 7): a draft cited
    # only to prior approved answers is not corroborated by current evidence.
    if cited and all(c.source_type == "approved_answer" for c in cited):
        reasons.append(
            "answer relies only on a reused approved answer; not corroborated by "
            "current evidence (policy/control/attestation)"
        )
    if injection_refs & {c.chunk_id for c in cited}:
        reasons.append("cited evidence contains injection-like content; flagged for review")

    needs_review = (
        bool(reasons)
        or draft.outcome not in ANSWERED_OUTCOMES
        or band != ConfidenceBand.HIGH
    )
    review_reason: str | None = None
    if reasons:
        review_reason = "; ".join(reasons)
    elif band != ConfidenceBand.HIGH:
        review_reason = f"composite confidence below high (band={band.value})"

    evidence_refs = [
        EvidenceRef(
            chunk_id=c.chunk_id,
            source_type=c.source_type,
            source_id=c.source_id,
            title=c.title,
        )
        for c in cited
    ]
    return GeneratedAnswer(
        question=question,
        outcome=draft.outcome,
        short_answer=draft.short_answer.strip(),
        answer=draft.answer.strip(),
        claim=draft.claim.strip(),
        scope=draft.scope.strip(),
        exceptions=draft.exceptions.strip(),
        evidence_refs=evidence_refs,
        confidence=score,
        confidence_band=band,
        confidence_factors=factors,
        needs_human_review=needs_review,
        review_reason=review_reason,
        freshness_status=_freshness(session, org.id, cited),
        generated_by=generated_by,
    )


def _ad_hoc_question(session: Session, org: Organization, text: str) -> Question:
    """Get-or-create the ad-hoc questionnaire, then create a Question for this text.

    Answers require a Question (FK); ad-hoc API questions are materialized here so the
    answer keeps full referential integrity and audit lineage without a schema change.
    """
    questionnaire = session.scalar(
        select(Questionnaire).where(
            Questionnaire.org_id == org.id, Questionnaire.title == _AD_HOC_QUESTIONNAIRE
        )
    )
    if questionnaire is None:
        questionnaire = Questionnaire(
            org_id=org.id, title=_AD_HOC_QUESTIONNAIRE, status="ad_hoc"
        )
        session.add(questionnaire)
        session.flush()
    question = Question(org_id=org.id, questionnaire_id=questionnaire.id, text=text)
    session.add(question)
    session.flush()
    return question


def persist_answer(
    session: Session,
    *,
    org: Organization,
    ga: GeneratedAnswer,
    question: Question | None = None,
) -> Answer:
    """Persist a generated answer + an audit_log entry. Caller commits.

    Links to an existing ``question`` (the Phase 5 workspace path) when given;
    otherwise materializes an ad-hoc question (the /answer debug endpoint).
    """
    if question is None:
        question = _ad_hoc_question(session, org, ga.question)
    answer = Answer(
        org_id=org.id,
        question_id=question.id,
        short_answer=ga.short_answer[:512] or None,
        answer_text=ga.answer or None,
        claim=ga.claim or None,
        scope=ga.scope or None,
        evidence_refs=[ref.model_dump() for ref in ga.evidence_refs],
        exceptions=ga.exceptions or None,
        confidence=ga.confidence_band.value,
        outcome=ga.outcome.value,
        needs_human_review=ga.needs_human_review,
        review_reason=ga.review_reason,
        freshness_status=ga.freshness_status,
        generated_by=ga.generated_by,
    )
    session.add(answer)
    session.flush()
    session.add(
        AuditLog(
            org_id=org.id,
            actor=ga.generated_by or "system:generate",
            action="answer.generate",
            target_type="answer",
            target_id=answer.id,
            # Counts/labels only — never answer text or evidence content.
            payload={
                "outcome": ga.outcome.value,
                "confidence_band": ga.confidence_band.value,
                "confidence": ga.confidence,
                "needs_human_review": ga.needs_human_review,
                "evidence_count": len(ga.evidence_refs),
            },
        )
    )
    return answer
