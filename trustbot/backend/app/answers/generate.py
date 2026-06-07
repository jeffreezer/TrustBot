"""Fixed retrieve-then-answer pipeline — respond mode (Milestone 1, 05 §5-§9).

Flow, deliberately fixed (CLAUDE.md principle 6 — no agentic loop / decomposition yet):

    retrieve (org-scoped, customer-shareable) → draft (generator, respond posture) →
    resolve citations → resolve provided documents + remediation (the register) →
    downgrade gates → composite confidence → review-flag validators → GeneratedAnswer

Posture is honest-affirmative (the vendor answering for itself), but the safety stance is
unchanged: every branch fails closed. An affirmative that cites no controlling owned
control/policy/attestation, or a provided report with an open finding lacking a target
date, is *downgraded* to ``needs_input`` — never a confident guess (principle 1). Drafts
are never auto-emitted; a human approves in Phase 5.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Answer,
    ApprovedAnswer,
    AuditLog,
    Control,
    Evidence,
    Finding,
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
from .prompts import detect_injection, respond_system_instructions
from .schema import (
    RESPOND_DRAFTED,
    AnswerDraft,
    CandidateDocument,
    CitedEvidence,
    ConfidenceBand,
    EvidenceRef,
    GeneratedAnswer,
    ProvidedDocument,
    RespondOutcome,
)
from .validate import (
    CONTROLLING_SOURCE_TYPES,
    FindingStatus,
    acceptable_basis_gate,
    open_findings_gate,
    run_review_checks,
)

# evidence_type → certification the org can therefore claim (attestation records).
_ATTESTATION_CERTS = {
    "soc2_report": "soc 2",
    "iso_certificate": "iso 27001",
    "pci_aoc": "pci dss",
}
# Cited source types that are themselves provide-able documents (Evidence rows).
_DOCUMENT_SOURCE_TYPES = frozenset({"evidence", "policy"})
# Question-text cues → the attestation document_kind the request names (05 §7).
_REQUESTED_KIND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("soc2_report", re.compile(r"\bsoc\s*2\b|\bsoc\s*ii\b|\bsoc2\b|service organization control 2")),
    ("iso_certificate", re.compile(r"\biso\s*/?\s*(?:iec\s*)?27001\b")),
    ("pci_aoc", re.compile(r"\bpci(?:\s*dss)?\b|attestation of compliance|\baoc\b")),
    ("pentest_report", re.compile(r"\bpen(?:etration)?[\s-]*test\b|\bpentest\b")),
)
_AD_HOC_QUESTIONNAIRE = "Ad-hoc questions (API)"
_MODE = "respond"
# A reused approved answer older than this carries a stale freshness signal and flags harder.
_APPROVED_ANSWER_STALE_DAYS = 365
# How many ranked documents to surface as candidates for a generic document-request.
_CANDIDATE_TOP_K = 25


@dataclass
class _DocResolution:
    """Outcome of resolving a document-request (05 §7-§8)."""

    provided: list[ProvidedDocument] = field(default_factory=list)
    findings: list[FindingStatus] = field(default_factory=list)
    missing_kinds: set[str] = field(default_factory=set)
    # Generic request: attachment deferred to a human + the candidate picker.
    selection_required: bool = False
    candidates: list[CandidateDocument] = field(default_factory=list)


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


def _resolve_reused_approvals(
    session: Session, org_id: uuid.UUID, cited: list[CitedEvidence]
) -> list[ApprovedAnswer]:
    """Resolve cited approved-answer chunks to real, org-owned ApprovedAnswer records (the
    same server-side discipline as documents — the model names a chunk; the system resolves
    it). A model-claimed approval that doesn't resolve simply isn't returned, so it can't act
    as a basis (it's treated as fabrication upstream)."""
    ids: set[uuid.UUID] = set()
    for c in cited:
        if c.source_type == "approved_answer" and c.source_id:
            try:
                ids.add(uuid.UUID(c.source_id))
            except (ValueError, TypeError):
                continue
    if not ids:
        return []
    return list(
        session.scalars(
            select(ApprovedAnswer).where(
                ApprovedAnswer.org_id == org_id, ApprovedAnswer.id.in_(ids)
            )
        ).all()
    )


def _approved_answer_validated_on(answer: ApprovedAnswer) -> date | None:
    """Last-approved/validated date for a reused answer — an explicit ``extra`` date if the
    source carried one, else the row's last-updated date as a proxy."""
    extra = answer.extra or {}
    for key in ("last_validated", "approved_at", "validated_at"):
        raw = extra.get(key)
        if isinstance(raw, str):
            try:
                return date.fromisoformat(raw.strip()[:10])
            except ValueError:
                continue
    if answer.updated_at:
        return answer.updated_at.date()
    return None


def _freshness(session: Session, org_id: uuid.UUID, cited: list[CitedEvidence]) -> str:
    """Derive a freshness label from the cited sources' validity / review / approval dates."""
    source_ids = {
        uuid.UUID(c.source_id)
        for c in cited
        if c.source_id and c.source_type in {"evidence", "policy", "control"}
    }
    approval_ids = {
        uuid.UUID(c.source_id)
        for c in cited
        if c.source_id and c.source_type == "approved_answer"
    }
    if not source_ids and not approval_ids:
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
    if approval_ids:
        approvals = session.scalars(
            select(ApprovedAnswer).where(
                ApprovedAnswer.org_id == org_id, ApprovedAnswer.id.in_(approval_ids)
            )
        ).all()
        for aa in approvals:
            validated = _approved_answer_validated_on(aa)
            if validated and (today - validated).days > _APPROVED_ANSWER_STALE_DAYS:
                statuses.add("stale")
            else:
                statuses.add("current")
    if "stale" in statuses:
        return "stale"
    if "review_due" in statuses:
        return "review_due"
    return "current" if statuses else "unknown"


def requested_document_kinds(question: str) -> set[str]:
    """The attestation artifact kinds a document-request explicitly names (05 §7). Used to
    attach the RIGHT artifact (the SOC 2 / ISO / PCI report), never whatever the answer was
    grounded in."""
    low = (question or "").lower()
    return {kind for kind, pat in _REQUESTED_KIND_PATTERNS if pat.search(low)}


def _findings_for(
    session: Session, org_id: uuid.UUID, docs: list[Evidence]
) -> list[FindingStatus]:
    if not docs:
        return []
    findings = session.scalars(
        select(Finding).where(
            Finding.org_id == org_id,
            Finding.source_document_id.in_([d.id for d in docs]),
            Finding.customer_shareable.is_(True),
        )
    ).all()
    return [
        FindingStatus(
            finding_id=str(f.id),
            external_ref=f.external_ref,
            status=f.status,
            has_target_date=f.target_remediation_date is not None,
        )
        for f in findings
    ]


def _candidate_documents(
    session: Session, org_id: uuid.UUID, question: str
) -> list[CandidateDocument]:
    """The org's customer_shareable evidence documents, relevance-ranked to the question for
    the analyst's picker (05 §8). Strictly org-scoped + shareable; documents only (collapsed
    from chunks). Ranking reuses the existing hybrid retrieval; documents it didn't surface
    are still listed (less relevant) so any shareable doc is selectable."""
    # Every Evidence row is a shareable document candidate (attestations, policies, etc.).
    universe = list(
        session.scalars(
            select(Evidence).where(
                Evidence.org_id == org_id,
                Evidence.customer_shareable.is_(True),
            )
        ).all()
    )
    if not universe:
        return []
    # Rank by the document-backed chunks (evidence/policy source types) the question hits.
    filters = RetrievalFilters(
        org_id=org_id,
        customer_shareable=True,
        source_types=list(_DOCUMENT_SOURCE_TYPES),
    )
    rank: dict[str, int] = {}
    for i, rc in enumerate(retrieve(session, query=question, filters=filters, top_k=_CANDIDATE_TOP_K)):
        sid = str(rc.source_id) if rc.source_id else None
        if sid and sid not in rank:
            rank[sid] = i
    universe.sort(key=lambda d: (rank.get(str(d.id), 10**6), d.title or ""))
    return [
        CandidateDocument(
            document_id=str(d.id), title=d.title, document_kind=d.document_kind
        )
        for d in universe
    ]


def _resolve_documents_and_findings(
    session: Session,
    org_id: uuid.UUID,
    question: str,
    draft: AnswerDraft,
    cited: list[CitedEvidence],
) -> _DocResolution:
    """Resolve a document-request (05 §7-§8).

    When the question NAMES attestation artifacts (SOC 2 / ISO / PCI / pentest), attach by
    ``document_kind`` so the actual attestation is attached — never a whitepaper as a
    stand-in — and report any requested kind missing from the corpus (routes to a human, no
    substitution). When the request is GENERIC (no specific artifact named), do NOT auto-
    attach: providing a document is a disclosure decision, so defer to a human and surface
    a relevance-ranked candidate picker instead. All queries are org-scoped +
    customer_shareable-gated; the model never names a document id."""
    if not draft.requires_document:
        return _DocResolution()

    requested = requested_document_kinds(question)
    if requested:
        docs = list(
            session.scalars(
                select(Evidence).where(
                    Evidence.org_id == org_id,
                    Evidence.customer_shareable.is_(True),
                    Evidence.document_kind.in_(requested),
                )
            ).all()
        )
        docs.sort(key=lambda d: (d.document_kind or "", d.title or ""))
        missing = requested - {d.document_kind for d in docs}
        provided = [ProvidedDocument(document_id=str(d.id), title=d.title) for d in docs]
        return _DocResolution(
            provided=provided,
            findings=_findings_for(session, org_id, docs),
            missing_kinds=missing,
        )

    # Generic document-request: never guess which document to disclose. Defer to a human and
    # surface candidates to choose from.
    return _DocResolution(
        selection_required=True,
        candidates=_candidate_documents(session, org_id, question),
    )


def _needs_input_answer(
    question: str, reason: str, generated_by: str
) -> GeneratedAnswer:
    """The fail-closed fallback (replaces review-mode 'unknown'): no draft, human required."""
    return GeneratedAnswer(
        question=question,
        outcome=RespondOutcome.NEEDS_INPUT,
        confidence=0.0,
        confidence_band=ConfidenceBand.NONE,
        confidence_factors={
            "relevance": 0.0,
            "authority": 0.0,
            "agreement": 0.0,
            "coverage": 0.0,
        },
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
    """Draft and validate one evidence-grounded respond-mode answer (or a needs-input
    fallback)."""
    question = question.strip()
    generator = generator or get_generation_provider()
    generated_by = f"{_MODE}:{generator.name}"
    if not question:
        return _needs_input_answer(question, "Empty question.", generated_by)

    # The question is untrusted inbound text. If it looks like it's trying to inject
    # instructions, flag it for a human rather than answering it (CLAUDE.md: treat such
    # content as data, never act on it).
    if detect_injection(question):
        return _needs_input_answer(
            question,
            "Question contains injection-like content; flagged for human review.",
            generated_by,
        )

    # Customer-facing answer: retrieve only customer-shareable evidence (the Phase 3
    # gate), so internal-only material can never enter the grounding in the first place.
    filters = RetrievalFilters(org_id=org.id, customer_shareable=True)
    retrieved = retrieve(session, query=question, filters=filters, top_k=top_k)
    if not retrieved:
        return _needs_input_answer(
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
            instructions=respond_system_instructions(org.name),
            grounding=tuple(grounding),
        )
    )
    try:
        draft = AnswerDraft.model_validate_json(raw)
    except ValidationError:
        return _needs_input_answer(
            question,
            "Generator returned a malformed or schema-invalid draft.",
            generated_by,
        )

    if draft.outcome == RespondOutcome.NEEDS_INPUT:
        note = draft.model_note.strip()
        if not note:
            try:
                note = (json.loads(raw) or {}).get("model_note", "")
            except (ValueError, TypeError):
                note = ""
        return _needs_input_answer(
            question,
            note or "No controlling control/policy/attestation found; a human must answer.",
            generated_by,
        )

    # Normalize cited refs before resolving/validating: models often echo the prompt's
    # "[ref:<id>]" label, returning "ref:<id>" or "[<id>]" instead of the bare chunk id.
    draft.evidence_refs = [r for r in (_normalize_ref(x) for x in draft.evidence_refs) if r]

    # Resolve citations to the actual retrieved chunks (org-scoped by construction).
    by_ref = {c.chunk_id: c for c in cited_all}
    cited = [by_ref[r] for r in draft.evidence_refs if r in by_ref]

    # Downgrade gate 1 — anti-fabrication: an affirmative must cite an acceptable basis
    # (policy/control/attestation OR a prior approved answer), else → needs_input (05).
    gate = acceptable_basis_gate(draft, cited)
    if gate:
        return _needs_input_answer(question, gate, generated_by)

    # Resolve a reused approved-answer basis server-side (provenance + freshness + a final
    # anti-fabrication check). A document-tier basis stands on its own; an approval-only
    # basis is valid but lower-authority and always human-reviewed.
    reused = _resolve_reused_approvals(session, org.id, cited)
    has_controlling = any(c.source_type in CONTROLLING_SOURCE_TYPES for c in cited)
    is_affirmative = draft.outcome in (RespondOutcome.ATTESTED, RespondOutcome.QUALIFIED)
    if is_affirmative and not has_controlling and not reused:
        # The only "basis" was an approved-answer reference that does not resolve to a real
        # approved record — treat as fabrication, not a basis.
        return _needs_input_answer(
            question,
            "affirmative basis (prior approved answer) did not resolve to an approved record",
            generated_by,
        )
    reused_only = is_affirmative and bool(reused) and not has_controlling

    # Resolve a document-request (named → auto-attach the attestation; generic → defer to a
    # human + surface candidates).
    docs = _resolve_documents_and_findings(session, org.id, question, draft, cited)
    provided_docs = docs.provided
    finding_statuses = docs.findings
    missing_kinds = docs.missing_kinds
    remediation_required = bool(finding_statuses)

    # Downgrade gate 2 — a provided report with an open finding and no target date can't
    # auto-draft (05 §9).
    date_gate = open_findings_gate(remediation_required, finding_statuses)
    if date_gate:
        return _needs_input_answer(question, date_gate, generated_by)

    score, factors, band = compute_confidence(question, cited)
    freshness_status = _freshness(session, org.id, cited)
    reasons = run_review_checks(
        draft,
        cited,
        grounding_refs=grounding_refs,
        available_certs=_available_certs(session, org.id),
        customer_facing=True,
    )
    if injection_refs & {c.chunk_id for c in cited}:
        reasons.append("cited evidence contains injection-like content; flagged for review")
    if missing_kinds:
        # A requested artifact isn't in the corpus — never substitute; a human supplies or
        # declines (05 §7).
        reasons.append(
            f"requested document(s) not in the evidence corpus: {sorted(missing_kinds)}; "
            "a human must supply or decline"
        )
    if docs.selection_required:
        # Generic document-request — the analyst chooses which artifact(s) to attach (05 §8).
        reasons.append("document selection required — choose the artifact(s) to attach")
    if reused_only:
        # Reuse of a human-approved answer is a candidate, not a bypass (principle 7): keep
        # the affirmative, but always re-confirm. Provenance is the cited approved_answer ref.
        provenance = ", ".join(
            sorted(a.question_external_id or a.source for a in reused)
        )
        reasons.append(
            "reused prior approval — confirm still accurate"
            + (f" (basis: approved answer {provenance})" if provenance else "")
        )
        if freshness_status == "stale":
            reasons.append("reused approved answer is stale — re-validate before sending")

    needs_review = (
        bool(reasons)
        or draft.outcome not in RESPOND_DRAFTED
        or band != ConfidenceBand.HIGH
        or reused_only  # never auto-emit a reused approval
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
        evidence_refs=evidence_refs,
        requires_document=draft.requires_document or bool(provided_docs),
        provided_documents=provided_docs,
        document_selection_required=docs.selection_required,
        candidate_documents=docs.candidates,
        remediation_required=remediation_required,
        finding_refs=[f.finding_id for f in finding_statuses],
        confidence=score,
        confidence_band=band,
        confidence_factors=factors,
        needs_human_review=needs_review,
        review_reason=review_reason,
        freshness_status=freshness_status,
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
        requires_document=ga.requires_document,
        provided_documents=[d.model_dump() for d in ga.provided_documents],
        document_selection_required=ga.document_selection_required,
        candidate_documents=[c.model_dump() for c in ga.candidate_documents],
        remediation_required=ga.remediation_required,
        finding_refs=list(ga.finding_refs),
        mode=_MODE,
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
                "mode": _MODE,
                "outcome": ga.outcome.value,
                "confidence_band": ga.confidence_band.value,
                "confidence": ga.confidence,
                "needs_human_review": ga.needs_human_review,
                "evidence_count": len(ga.evidence_refs),
                "requires_document": ga.requires_document,
                "document_selection_required": ga.document_selection_required,
                "remediation_required": ga.remediation_required,
            },
        )
    )
    return answer
