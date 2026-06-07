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
from ..config import settings
from ..providers import (
    AgentRound,
    DraftRequest,
    GenerationProvider,
    GroundingDoc,
    ToolResultMsg,
    get_generation_provider,
)
from ..retrieval import RetrievalFilters, RetrievedChunk, retrieve
from .agent_tools import TOOL_SPECS, audit_view, execute_tool
from .confidence import band_for, compute_confidence
from .prompts import decompose_instructions, detect_injection, respond_system_instructions
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
    SubAnswer,
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
    session: Session,
    org_id: uuid.UUID,
    question: str,
    recommended_ids: frozenset[str] = frozenset(),
) -> list[CandidateDocument]:
    """The org's customer_shareable evidence documents, relevance-ranked to the question for
    the analyst's picker (05 §8.5). Strictly org-scoped + shareable; documents only (collapsed
    from chunks). Ranking reuses the existing hybrid retrieval; documents it didn't surface
    are still listed (less relevant) so any shareable doc is selectable. Documents in
    ``recommended_ids`` (the governing doc the answer cited) are flagged and sorted first so
    the common case is a one-click confirm."""
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
    # Recommended first, then by relevance, then title.
    universe.sort(
        key=lambda d: (str(d.id) not in recommended_ids, rank.get(str(d.id), 10**6), d.title or "")
    )
    return [
        CandidateDocument(
            document_id=str(d.id),
            title=d.title,
            document_kind=d.document_kind,
            recommended=str(d.id) in recommended_ids,
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

    # No named attestation kind. Providing a document is a human disclosure decision, so NEVER
    # auto-attach (05 §8.5): always surface the analyst picker. The governing document the
    # answer cited (system resolves chunk→document; the model named no id) is pre-selected as
    # the recommended choice — the common case is a one-click confirm, but the analyst can
    # deselect it or pick other shareable artifacts. Nothing attaches until they confirm.
    cited_doc_ids: set[uuid.UUID] = set()
    for c in cited:
        if c.source_id and c.source_type in _DOCUMENT_SOURCE_TYPES:
            try:
                cited_doc_ids.add(uuid.UUID(c.source_id))
            except (ValueError, TypeError):
                continue
    recommended: frozenset[str] = frozenset()
    if cited_doc_ids:
        # Only org-owned, customer_shareable cited docs are eligible to recommend.
        rec_rows = session.scalars(
            select(Evidence.id).where(
                Evidence.org_id == org_id,
                Evidence.id.in_(cited_doc_ids),
                Evidence.customer_shareable.is_(True),
            )
        ).all()
        recommended = frozenset(str(i) for i in rec_rows)
    return _DocResolution(
        selection_required=True,
        candidates=_candidate_documents(session, org_id, question, recommended),
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


# --- adaptive retrieval loop (Phase 6) -------------------------------------

# Cheap, deterministic routing cues: a compound / conditional / enumerated question goes to
# the loop; a simple single-fact question keeps the one-shot path (no cost regression).
_LOOP_CUES = re.compile(r"\bif\s+(?:yes|so|applicable|not|any)\b", re.IGNORECASE)
_ENUM_LINE = re.compile(r"(?:^|\n)\s*(?:\d+[.)]|[-*•]|[a-d][.)])\s", re.MULTILINE)
# Inline enumerators like "1. ... 2. ... 3." (a space after the marker, not a decimal).
_ENUM_INLINE = re.compile(r"(?<!\d)[1-9][.)]\s+\S")


def _is_compound(question: str) -> bool:
    """True for compound/conditional/enumerated questions that warrant decomposition; False
    for a simple single-fact ask (06 §5 routing). Pure + cheap — no model call. A simple
    question is never decomposed and keeps the one-shot path (no cost regression)."""
    q = question.strip()
    low = q.lower()
    if low.count("?") >= 2:  # multiple explicit sub-questions
        return True
    if _LOOP_CUES.search(low):  # conditional follow-up, e.g. "if yes, attach ..."
        return True
    if _ENUM_LINE.search(q):  # bulleted / line-start enumerated multi-part
        return True
    if len(_ENUM_INLINE.findall(q)) >= 2:  # "1. ... 2. ..." inline multi-part
        return True
    if ";" in q:
        return True
    if low.count(" and ") >= 2 and len(q) > 120:  # several and-joined asks
        return True
    return False


@dataclass
class _Gather:
    """The output of the gather step (one-shot or loop): a structured draft (or a needs-input
    reason) plus the citeable pool + the audit trail. Downstream is identical for both."""

    draft: AnswerDraft | None = None
    reason: str | None = None
    cited_all: list[CitedEvidence] = field(default_factory=list)
    grounding_refs: list[str] = field(default_factory=list)
    injection_refs: set[str] = field(default_factory=set)
    tool_audit: list[dict] = field(default_factory=list)
    path: str = "fixed"


def _parse_draft(raw: str) -> tuple[AnswerDraft | None, str | None]:
    """Validate a generator draft; return ``(draft, None)`` or ``(None, reason)`` for a
    malformed draft or a model-signalled needs_input."""
    try:
        draft = AnswerDraft.model_validate_json(raw)
    except ValidationError:
        return None, "Generator returned a malformed or schema-invalid draft."
    if draft.outcome == RespondOutcome.NEEDS_INPUT:
        note = draft.model_note.strip()
        if not note:
            try:
                note = (json.loads(raw) or {}).get("model_note", "")
            except (ValueError, TypeError):
                note = ""
        return None, note or "No controlling control/policy/attestation found; a human must answer."
    return draft, None


def _gather_fixed(
    session: Session, org: Organization, question: str, generator: GenerationProvider, *, top_k
) -> _Gather:
    """Phase 4 one-shot: a single hybrid search → draft. Used for simple questions."""
    filters = RetrievalFilters(org_id=org.id, customer_shareable=True)
    retrieved = retrieve(session, query=question, filters=filters, top_k=top_k)
    if not retrieved:
        return _Gather(reason="No customer-shareable evidence was retrieved for this question.")
    cited_all, grounding = _grounding_from_retrieved(retrieved)
    raw = generator.draft(
        DraftRequest(
            question=question,
            instructions=respond_system_instructions(org.name),
            grounding=tuple(grounding),
        )
    )
    draft, reason = _parse_draft(raw)
    return _Gather(
        draft=draft,
        reason=reason,
        cited_all=cited_all,
        grounding_refs=[d.ref for d in grounding],
        injection_refs={c.chunk_id for c in cited_all if detect_injection(c.text)},
        path="fixed",
    )


def _gather_via_loop(
    session: Session, org: Organization, question: str, generator: GenerationProvider, *, top_k
) -> _Gather:
    """The bounded adaptive loop (06 §5): the model searches/refines via read-only org-scoped
    tools, then emits the structured draft. Every gathered chunk joins the citeable pool; every
    tool call is recorded for the audit trail. Bounded by an iteration cap + tool-call budget;
    on exhaustion without a draft → needs_input (downstream)."""
    system = respond_system_instructions(org.name)
    k = top_k or settings.retrieval_top_k
    max_iters = settings.agent_max_iterations
    max_calls = settings.agent_max_tool_calls

    history: list[AgentRound] = []
    pool: dict[str, CitedEvidence] = {}
    audit: list[dict] = []
    calls_used = 0
    draft: AnswerDraft | None = None
    reason: str | None = None

    for i in range(max_iters):
        force_final = (i == max_iters - 1) or (calls_used >= max_calls)
        turn = generator.agent_turn(
            system=system,
            question=question,
            history=tuple(history),
            tools=TOOL_SPECS,
            force_final=force_final,
        )
        if turn.draft_json is not None:
            draft, reason = _parse_draft(turn.draft_json)
            break
        if not turn.tool_calls:
            break  # the model neither searched nor drafted — stop (→ needs_input)
        results: list[ToolResultMsg] = []
        for call in turn.tool_calls:
            if calls_used >= max_calls:
                break
            audit.append(audit_view(call))  # metadata only — never tool content
            result, new_cited = execute_tool(
                session, org, call, customer_facing=True, top_k=k
            )
            calls_used += 1
            for c in new_cited:
                pool.setdefault(c.chunk_id, c)
            results.append(
                ToolResultMsg(call_id=call.id, name=call.name, content=json.dumps(result))
            )
        history.append(AgentRound(assistant=turn, results=tuple(results)))

    cited_all = list(pool.values())
    if draft is None and reason is None:
        reason = (
            "The adaptive search did not find sufficient evidence to answer; a human must "
            "review."
        )
    return _Gather(
        draft=draft,
        reason=reason,
        cited_all=cited_all,
        grounding_refs=[c.chunk_id for c in cited_all],
        injection_refs={c.chunk_id for c in cited_all if detect_injection(c.text)},
        tool_audit=audit,
        path="loop",
    )


def _supports_tools(generator: GenerationProvider) -> bool:
    fn = getattr(generator, "supports_tools", None)
    return bool(callable(fn) and fn())


def _gather(
    session: Session,
    org: Organization,
    question: str,
    generator: GenerationProvider,
    *,
    top_k: int | None,
    use_loop: bool,
) -> _Gather:
    """Gather evidence for ONE focused question. ``use_loop`` runs the adaptive loop (focused
    reformulating searches, used per sub-question); otherwise the one-shot path. Both are
    hard-gated to customer_shareable."""
    if use_loop and settings.agent_loop_enabled and _supports_tools(generator):
        return _gather_via_loop(session, org, question, generator, top_k=top_k)
    return _gather_fixed(session, org, question, generator, top_k=top_k)


def generate_answer(
    session: Session,
    *,
    org: Organization,
    question: str,
    top_k: int | None = None,
    generator: GenerationProvider | None = None,
) -> GeneratedAnswer:
    """Answer one questionnaire question. A simple question takes the one-shot path; a compound
    question is decomposed into atomic sub-questions, each answered independently through the
    full pipeline (loop + validators), then recomposed per-part (06 §5)."""
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

    # Compound question → decompose + answer each part independently + recompose. A simple
    # single-fact question is never decomposed and keeps the one-shot path (no cost regression).
    if settings.agent_loop_enabled and _supports_tools(generator) and _is_compound(question):
        return _answer_compound(session, org, question, generator, generated_by, top_k=top_k)
    return _answer_one(
        session, org, question, generator, generated_by, top_k=top_k, use_loop=False
    )


def _answer_one(
    session: Session,
    org: Organization,
    question: str,
    generator: GenerationProvider,
    generated_by: str,
    *,
    top_k: int | None,
    use_loop: bool,
) -> GeneratedAnswer:
    """Answer ONE focused question through the full retrieve→draft→validate→resolve pipeline.
    Used directly for a simple question (one-shot) and per sub-question for a compound one
    (with the adaptive loop for its own focused searches)."""
    gathered = _gather(session, org, question, generator, top_k=top_k, use_loop=use_loop)
    cited_all = gathered.cited_all
    grounding_refs = gathered.grounding_refs
    injection_refs = gathered.injection_refs

    def _fail(reason: str) -> GeneratedAnswer:
        """needs_input fallback that still carries the retrieval path + tool-call trail."""
        ans = _needs_input_answer(question, reason, generated_by)
        ans.retrieval_path = gathered.path
        ans.tool_calls = gathered.tool_audit
        return ans

    if gathered.draft is None:
        return _fail(gathered.reason or "No sufficient evidence; a human must review.")
    draft = gathered.draft

    # Normalize cited refs before resolving/validating: models often echo the prompt's
    # "[ref:<id>]" label, returning "ref:<id>" or "[<id>]" instead of the bare chunk id.
    draft.evidence_refs = [r for r in (_normalize_ref(x) for x in draft.evidence_refs) if r]

    # Resolve citations to the actual gathered chunks (org-scoped by construction).
    by_ref = {c.chunk_id: c for c in cited_all}
    cited = [by_ref[r] for r in draft.evidence_refs if r in by_ref]

    # Downgrade gate 1 — anti-fabrication: an affirmative must cite an acceptable basis
    # (policy/control/attestation OR a prior approved answer), else → needs_input (05).
    gate = acceptable_basis_gate(draft, cited)
    if gate:
        return _fail(gate)

    # Resolve a reused approved-answer basis server-side (provenance + freshness + a final
    # anti-fabrication check). A document-tier basis stands on its own; an approval-only
    # basis is valid but lower-authority and always human-reviewed.
    reused = _resolve_reused_approvals(session, org.id, cited)
    has_controlling = any(c.source_type in CONTROLLING_SOURCE_TYPES for c in cited)
    is_affirmative = draft.outcome in (RespondOutcome.ATTESTED, RespondOutcome.QUALIFIED)
    if is_affirmative and not has_controlling and not reused:
        # The only "basis" was an approved-answer reference that does not resolve to a real
        # approved record — treat as fabrication, not a basis.
        return _fail(
            "affirmative basis (prior approved answer) did not resolve to an approved record"
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
        return _fail(date_gate)

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
        retrieval_path=gathered.path,
        tool_calls=gathered.tool_audit,
    )


# --- explicit decomposition of compound questions (06 §5) ------------------

# Worst-wins ordering for combining the per-part freshness signal.
_FRESHNESS_RANK = {"current": 0, "unknown": 1, "review_due": 2, "stale": 3}


def _decompose(
    session: Session, org: Organization, question: str, generator: GenerationProvider
) -> list[str]:
    """Split a compound question into bounded atomic sub-questions (one model split step). On
    any failure, degrade to the single question — never crash the answer path."""
    try:
        parts = generator.decompose(
            question=question,
            instructions=decompose_instructions(org.name),
            max_parts=settings.agent_max_subquestions,
        )
    except Exception:  # noqa: BLE001 — a split failure degrades to one question, never fails closed-open
        return [question]
    cleaned = [p.strip() for p in parts if isinstance(p, str) and p.strip()]
    return cleaned[: settings.agent_max_subquestions] or [question]


def _answer_compound(
    session: Session,
    org: Organization,
    question: str,
    generator: GenerationProvider,
    generated_by: str,
    *,
    top_k: int | None,
) -> GeneratedAnswer:
    """Decompose → answer each sub-question independently through the full pipeline → recompose
    (06 §5). Each part gets focused grounding (its own adaptive loop) and the full validator
    stack, rather than one model pass juggling everything."""
    sub_questions = _decompose(session, org, question, generator)
    if len(sub_questions) <= 1:
        # Not splittable — answer the question once (still with the focused loop).
        return _answer_one(
            session, org, sub_questions[0] if sub_questions else question, generator,
            generated_by, top_k=top_k, use_loop=True,
        )
    parts = [
        _answer_one(session, org, sq, generator, generated_by, top_k=top_k, use_loop=True)
        for sq in sub_questions
    ]
    return _recompose(question, sub_questions, parts, generated_by)


def _recompose(
    question: str,
    sub_questions: list[str],
    parts: list[GeneratedAnswer],
    generated_by: str,
) -> GeneratedAnswer:
    """Combine independently-answered parts into one coherent, per-part answer (06 §5). Each
    part keeps its own outcome + citations; an unsupported part is flagged, never dropped.

    Combined outcome: all parts attested → attested; mixed support (some qualified/negative,
    or some part unsupported) → qualified for what's supported (with the review flag); no part
    supported → needs_input.
    """
    answered = [p for p in parts if p.outcome != RespondOutcome.NEEDS_INPUT]
    unsupported_idx = [
        i for i, p in enumerate(parts) if p.outcome == RespondOutcome.NEEDS_INPUT
    ]
    if not answered:
        overall = RespondOutcome.NEEDS_INPUT
    elif unsupported_idx or any(p.outcome != RespondOutcome.ATTESTED for p in answered):
        overall = RespondOutcome.QUALIFIED
    else:
        overall = RespondOutcome.ATTESTED

    subs = [
        SubAnswer(
            sub_question=sq,
            outcome=p.outcome,
            short_answer=p.short_answer,
            answer=p.answer,
            evidence_refs=list(p.evidence_refs),
            needs_human_review=p.needs_human_review,
            review_reason=p.review_reason,
        )
        for sq, p in zip(sub_questions, parts)
    ]

    blocks: list[str] = []
    for i, (sq, p) in enumerate(zip(sub_questions, parts), start=1):
        if p.outcome == RespondOutcome.NEEDS_INPUT:
            body = "Needs human review — no approved evidence substantiates this part."
        else:
            body = (p.answer or p.short_answer or "").strip()
        blocks.append(f"{i}. {sq}\n{body}")
    answer_text = "\n\n".join(blocks)
    n_flag = len(unsupported_idx)
    short_answer = (
        f"Addressed {len(parts)} parts: {len(answered)} answered"
        + (f", {n_flag} need human review." if n_flag else ".")
    )

    # Union per-part citations (deduped); per-part attribution stays in sub_answers.
    evidence_refs: list[EvidenceRef] = []
    seen_refs: set[str] = set()
    for p in parts:
        for r in p.evidence_refs:
            if r.chunk_id not in seen_refs:
                seen_refs.add(r.chunk_id)
                evidence_refs.append(r)

    # Aggregate document-provision across parts.
    provided: list[ProvidedDocument] = []
    candidates: list[CandidateDocument] = []
    finding_refs: list[str] = []
    seen_docs: set[str] = set()
    seen_cands: set[str] = set()
    seen_findings: set[str] = set()
    requires_document = selection_required = remediation_required = False
    for p in parts:
        requires_document = requires_document or p.requires_document
        selection_required = selection_required or p.document_selection_required
        remediation_required = remediation_required or p.remediation_required
        for d in p.provided_documents:
            if d.document_id not in seen_docs:
                seen_docs.add(d.document_id)
                provided.append(d)
        for c in p.candidate_documents:
            if c.document_id not in seen_cands:
                seen_cands.add(c.document_id)
                candidates.append(c)
        for f in p.finding_refs:
            if f not in seen_findings:
                seen_findings.add(f)
                finding_refs.append(f)

    conf = min((p.confidence for p in answered), default=0.0)
    band = band_for(conf) if answered else ConfidenceBand.NONE

    freshness = "current"
    worst = -1
    for p in parts:
        rank = _FRESHNESS_RANK.get(p.freshness_status or "unknown", 1)
        if rank > worst:
            worst, freshness = rank, (p.freshness_status or "unknown")

    reasons: list[str] = []
    if unsupported_idx:
        reasons.append(
            "unsupported part(s) flagged for human review: "
            + "; ".join(sub_questions[i] for i in unsupported_idx)
        )
    reasons.extend(p.review_reason for p in answered if p.needs_human_review and p.review_reason)
    needs_review = (
        bool(unsupported_idx)
        or any(p.needs_human_review for p in parts)
        or overall != RespondOutcome.ATTESTED
    )
    review_reason = "; ".join(dict.fromkeys(reasons)) or None

    tool_calls: list[dict] = [{"tool": "decompose", "sub_questions": list(sub_questions)}]
    for p in parts:
        tool_calls.extend(p.tool_calls)

    return GeneratedAnswer(
        question=question,
        outcome=overall,
        short_answer=short_answer,
        answer=answer_text,
        claim="",
        scope="",
        evidence_refs=evidence_refs,
        requires_document=requires_document or bool(provided),
        provided_documents=provided,
        document_selection_required=selection_required,
        candidate_documents=candidates,
        remediation_required=remediation_required,
        finding_refs=finding_refs,
        confidence=conf,
        confidence_band=band,
        confidence_factors={},
        needs_human_review=needs_review,
        review_reason=review_reason,
        freshness_status=freshness,
        generated_by=generated_by,
        retrieval_path="decomposed",
        tool_calls=tool_calls,
        sub_answers=subs,
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
        sub_answers=[s.model_dump() for s in ga.sub_answers],
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
                "retrieval_path": ga.retrieval_path,
                "tool_call_count": len(ga.tool_calls),
                "sub_answer_count": len(ga.sub_answers),
            },
        )
    )
    # Adaptive loop: record HOW the agent gathered evidence — the ordered, metadata-only
    # tool-call trail (tool + query/id; never content) — so the evidence path is auditable.
    if ga.tool_calls:
        session.add(
            AuditLog(
                org_id=org.id,
                actor=ga.generated_by or "system:generate",
                action="answer.retrieval",
                target_type="answer",
                target_id=answer.id,
                payload={"path": ga.retrieval_path, "tool_calls": ga.tool_calls},
            )
        )
    return answer
