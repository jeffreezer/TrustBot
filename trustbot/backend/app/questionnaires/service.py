"""Review workspace service (Phase 5): intake → draft → review → export.

Every function is **org-scoped** (single-tenant demo today; the org is resolved by the
route and threaded through, so real auth slots in here later without touching queries).
Review actions write both an ``answer_reviews`` row and an ``audit_log`` entry; audit
payloads carry **labels only** — never answer text, evidence content, or secrets.

The pure pieces (status transitions, CSV/Excel serialization) live at module level so
they unit-test without a database; the DB round-trip is verified end-to-end.
"""
from __future__ import annotations

import csv
import hashlib
import io
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..answers import detect_injection, generate_answer, persist_answer
from ..db.models import (
    Answer,
    AnswerReview,
    ApprovedAnswer,
    AuditLog,
    Evidence,
    Finding,
    GenerationJob,
    KnowledgeChunk,
    Organization,
    Question,
    Questionnaire,
)
from ..providers import GenerationProvider
from ..storage import get_storage, object_key_from_storage_path, sanitize_filename
from .parse import parse_questionnaire

# Reviewer actions → the review_status they transition the answer to. "save_to_library"
# implies acceptance, so it also lands 'approved'.
ACTION_STATUS: dict[str, str] = {
    "approve": "approved",
    "edit": "edited",
    "reject": "rejected",
    "request_evidence": "needs_evidence",
    "save_to_library": "approved",
}
REVIEW_ACTIONS = frozenset(ACTION_STATUS)

# Human-finalized statuses that regenerate must never supersede or overwrite.
PROTECTED_STATUSES = frozenset({"approved", "edited"})

EXPORT_COLUMNS = [
    "id", "domain", "question", "outcome", "review_status", "needs_human_review",
    "confidence", "short_answer", "answer", "documents", "remediation", "evidence",
    "freshness", "reviewer",
]


def next_review_status(action: str) -> str:
    """Map a reviewer action to the resulting review_status (pure; raises on unknown)."""
    try:
        return ACTION_STATUS[action]
    except KeyError as exc:
        raise ValueError(f"unknown review action: {action!r}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- intake -----------------------------------------------------------------

def create_questionnaire(
    session: Session,
    *,
    org: Organization,
    data: bytes,
    filename: str,
    content_type: str | None = None,
) -> Questionnaire:
    """Parse + store an uploaded questionnaire and create its question rows.

    The file is stored via the adapter with a recorded hash and treated strictly as
    data (never executed). Each question is screened for injection-like content; the
    count is recorded in the audit log (and the draft pipeline re-screens per question).
    """
    parsed = parse_questionnaire(data, filename=filename, content_type=content_type)

    storage = get_storage()
    storage.ensure_bucket()
    suffix = Path(filename).suffix.lstrip(".").lower() or None
    questionnaire = Questionnaire(
        org_id=org.id,
        title=Path(filename).stem.replace("_", " ") or "Questionnaire",
        original_filename=filename,
        storage_path="",
        file_hash=_sha256(data),
        source_format=suffix,
        status="uploaded",
    )
    session.add(questionnaire)
    session.flush()  # assign id for the storage key
    key = f"org/{org.id}/questionnaires/{questionnaire.id}/{sanitize_filename(filename)}"
    questionnaire.storage_path = storage.put(
        key, data, content_type=content_type or "application/octet-stream"
    )

    flagged = 0
    for p in parsed:
        if detect_injection(p.text):
            flagged += 1
        session.add(
            Question(
                org_id=org.id,
                questionnaire_id=questionnaire.id,
                external_id=p.external_id,
                domain=p.domain,
                text=p.text,
                row_index=p.row_index,
            )
        )
    session.flush()
    session.add(
        AuditLog(
            org_id=org.id,
            actor="system:intake",
            action="questionnaire.upload",
            target_type="questionnaire",
            target_id=questionnaire.id,
            payload={
                "questions": len(parsed),
                "injection_flagged": flagged,
                "format": suffix,
            },
        )
    )
    return questionnaire


# --- queries ----------------------------------------------------------------

def _latest_answers(
    session: Session, org: Organization, questionnaire_id: uuid.UUID
) -> dict[uuid.UUID, Answer]:
    """The live (non-superseded) answer per question for a questionnaire.

    Regenerate supersedes prior drafts (see ``generate_drafts``), so there is at most one
    non-superseded answer per question; the created_at ordering is just a defensive
    tiebreak."""
    answers = session.scalars(
        select(Answer)
        .join(Question, Answer.question_id == Question.id)
        .where(
            Question.questionnaire_id == questionnaire_id,
            Answer.org_id == org.id,
            Answer.superseded_at.is_(None),
        )
        .order_by(Answer.created_at.asc())
    ).all()
    return {a.question_id: a for a in answers}  # asc → last write wins = latest


def list_questionnaires(session: Session, *, org: Organization) -> list[dict]:
    questionnaires = session.scalars(
        select(Questionnaire)
        .where(Questionnaire.org_id == org.id)
        .order_by(Questionnaire.created_at.desc())
    ).all()
    out: list[dict] = []
    for q in questionnaires:
        total = session.scalar(
            select(func.count()).select_from(Question).where(
                Question.questionnaire_id == q.id
            )
        )
        answered = len(_latest_answers(session, org, q.id))
        out.append(
            {
                "id": str(q.id),
                "title": q.title,
                "status": q.status,
                "source_format": q.source_format,
                "question_count": total or 0,
                "answered_count": answered,
                "created_at": q.created_at.isoformat() if q.created_at else None,
            }
        )
    return out


def _question_row(q: Question, answer: Answer | None) -> dict:
    return {
        "id": str(q.id),
        "external_id": q.external_id,
        "domain": q.domain,
        "text": q.text,
        "row_index": q.row_index,
        "answer_id": str(answer.id) if answer else None,
        "status": answer.review_status if answer else "undrafted",
        "outcome": answer.outcome if answer else None,
        "confidence": answer.confidence if answer else None,
        "needs_human_review": answer.needs_human_review if answer else None,
    }


def get_questionnaire_detail(
    session: Session, *, org: Organization, questionnaire_id: uuid.UUID
) -> dict | None:
    questionnaire = session.scalar(
        select(Questionnaire).where(
            Questionnaire.id == questionnaire_id, Questionnaire.org_id == org.id
        )
    )
    if questionnaire is None:
        return None
    questions = session.scalars(
        select(Question)
        .where(Question.questionnaire_id == questionnaire.id, Question.org_id == org.id)
        .order_by(Question.row_index.asc())
    ).all()
    latest = _latest_answers(session, org, questionnaire.id)
    return {
        "id": str(questionnaire.id),
        "title": questionnaire.title,
        "status": questionnaire.status,
        "source_format": questionnaire.source_format,
        "active_job": _active_job(session, org, questionnaire.id),
        "questions": [_question_row(q, latest.get(q.id)) for q in questions],
    }


def _active_job(
    session: Session, org: Organization, questionnaire_id: uuid.UUID
) -> dict | None:
    """The latest non-terminal generation job for this questionnaire, so a reopened tab
    resumes the progress view instead of looking idle. Org-scoped."""
    job = session.scalar(
        select(GenerationJob)
        .where(
            GenerationJob.questionnaire_id == questionnaire_id,
            GenerationJob.org_id == org.id,
            GenerationJob.status.in_(("pending", "running")),
        )
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        return None
    return {
        "job_id": str(job.id),
        "status": job.status,
        "total": job.total,
        "completed": job.completed,
    }


def _render_findings(
    session: Session, org: Organization, finding_ids: list
) -> list[dict]:
    """Customer-facing render of the linked findings (05 §9): org-scoped, customer_shareable
    only, and the internal-only ``owner`` field is never included. Sorted by severity."""
    ids = [u for u in (_safe_uuid(f) for f in (finding_ids or [])) if u]
    if not ids:
        return []
    findings = list(
        session.scalars(
            select(Finding).where(
                Finding.org_id == org.id,
                Finding.id.in_(ids),
                Finding.customer_shareable.is_(True),
            )
        ).all()
    )
    findings.sort(key=lambda f: (-(f.severity_rank or 0), f.external_ref or ""))
    return [
        {
            "id": str(f.id),
            "external_ref": f.external_ref,
            "title": f.title,
            "severity": f.severity,
            "status": f.status,
            "identified_date": f.identified_date.isoformat() if f.identified_date else None,
            "target_remediation_date": (
                f.target_remediation_date.isoformat() if f.target_remediation_date else None
            ),
            "remediated_date": f.remediated_date.isoformat() if f.remediated_date else None,
            "remediation_summary": f.remediation_summary,
        }
        for f in findings
    ]


def _answer_payload(session: Session, org: Organization, answer: Answer) -> dict:
    provided = []
    for d in answer.provided_documents or []:
        doc_id = d.get("document_id") if isinstance(d, dict) else None
        if not doc_id:
            continue
        provided.append(
            {
                "document_id": doc_id,
                "title": d.get("title"),
                # The only way to fetch the bytes: org-scoped, audited, never a bearer link.
                "download_url": f"/documents/{doc_id}/download",
            }
        )
    findings = (
        _render_findings(session, org, answer.finding_refs)
        if answer.remediation_required
        else []
    )
    return {
        "id": str(answer.id),
        "mode": answer.mode,
        "outcome": answer.outcome,
        "short_answer": answer.short_answer,
        "answer": answer.answer_text,
        "claim": answer.claim,
        "scope": answer.scope,
        "requires_document": answer.requires_document,
        "provided_documents": provided,
        # Generic document-request picker (05 §8): the analyst chooses which to attach.
        "document_selection_required": answer.document_selection_required,
        "candidate_documents": answer.candidate_documents or [],
        "remediation_required": answer.remediation_required,
        "findings": findings,
        "confidence": answer.confidence,
        "needs_human_review": answer.needs_human_review,
        "review_reason": answer.review_reason,
        # Phase 8: injection-like content detected (question/evidence), neutralized + flagged.
        "injection_flagged": answer.injection_flagged,
        "review_status": answer.review_status,
        "freshness_status": answer.freshness_status,
        "evidence_refs": answer.evidence_refs or [],
        "generated_by": answer.generated_by,
        # Per-part breakdown for a decomposed compound answer (06).
        "sub_answers": answer.sub_answers or [],
    }


def get_question_detail(
    session: Session, *, org: Organization, question_id: uuid.UUID
) -> dict | None:
    """Question + its latest draft + the cited evidence (text for the right pane)."""
    question = session.scalar(
        select(Question).where(Question.id == question_id, Question.org_id == org.id)
    )
    if question is None:
        return None
    answer = session.scalar(
        select(Answer)
        .where(
            Answer.question_id == question.id,
            Answer.org_id == org.id,
            Answer.superseded_at.is_(None),
        )
        .order_by(Answer.created_at.desc())
        .limit(1)
    )
    citations: list[dict] = []
    if answer and answer.evidence_refs:
        ref_ids = []
        for ref in answer.evidence_refs:
            try:
                ref_ids.append(uuid.UUID(ref["chunk_id"]))
            except (KeyError, ValueError, TypeError):
                continue
        if ref_ids:
            # Org-scoped: only this org's chunks can ever be returned as citations.
            chunks = session.scalars(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.org_id == org.id, KnowledgeChunk.id.in_(ref_ids)
                )
            ).all()
            by_id = {c.id: c for c in chunks}
            for ref in answer.evidence_refs:
                chunk = by_id.get(_safe_uuid(ref.get("chunk_id")))
                if chunk is None:
                    continue
                citations.append(
                    {
                        "chunk_id": str(chunk.id),
                        "source_type": chunk.source_type,
                        "title": (chunk.meta or {}).get("title") or ref.get("title"),
                        "text": chunk.chunk_text,
                        "confidentiality": (chunk.meta or {}).get("confidentiality"),
                        "customer_shareable": (chunk.meta or {}).get("customer_shareable"),
                    }
                )
    return {
        "question": {
            "id": str(question.id),
            "external_id": question.external_id,
            "domain": question.domain,
            "text": question.text,
        },
        "answer": _answer_payload(session, org, answer) if answer else None,
        "citations": citations,
    }


def _safe_uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# --- draft generation -------------------------------------------------------

def generate_drafts(
    session: Session,
    *,
    org: Organization,
    questionnaire_id: uuid.UUID,
    regenerate: bool = False,
    generator: GenerationProvider | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Generate a Phase-4 draft for each question, committing **incrementally**.

    Each drafted answer is committed as it is produced (supersede-old + new + audit,
    atomically), so progress is observable and a failure/restart partway keeps the work
    already done. A single question whose generation fails (e.g. a provider timeout) is
    left undrafted and the loop continues — it doesn't stall the whole run. ``on_progress``
    (if given) is called with ``(processed, total)`` after each question, so a job worker
    can report live progress. Skips already-drafted questions unless ``regenerate``;
    approved/edited answers are never superseded."""
    questionnaire = session.scalar(
        select(Questionnaire).where(
            Questionnaire.id == questionnaire_id, Questionnaire.org_id == org.id
        )
    )
    if questionnaire is None:
        raise LookupError("questionnaire not found")
    questions = session.scalars(
        select(Question)
        .where(Question.questionnaire_id == questionnaire.id, Question.org_id == org.id)
        .order_by(Question.row_index.asc())
    ).all()
    live = _latest_answers(session, org, questionnaire.id)  # the non-superseded answer/q

    total = len(questions)
    generated = skipped = preserved = failed = processed = 0
    now = datetime.now(timezone.utc)

    def _tick() -> None:
        nonlocal processed
        processed += 1
        if on_progress is not None:
            on_progress(processed, total)

    for q in questions:
        current = live.get(q.id)
        if current is not None and not regenerate:
            skipped += 1
            _tick()
            continue
        # Never replace human-finalized work: an approved/edited answer is left live and
        # untouched (audit_log is likewise never superseded — auditability first).
        if current is not None and current.review_status in PROTECTED_STATUSES:
            preserved += 1
            _tick()
            continue
        try:
            ga = generate_answer(session, org=org, question=q.text, generator=generator)
        except Exception:  # noqa: BLE001 - one question's failure must not stall the run
            # Leave this question undrafted; incremental commits keep the rest. No detail
            # is surfaced or logged here (could carry provider/PII content).
            session.rollback()
            failed += 1
            _tick()
            continue
        # Supersede the prior draft only now that a replacement exists, so a failed draft
        # never leaves a question with nothing live.
        if current is not None:
            current.superseded_at = now
        persist_answer(session, org=org, ga=ga, question=q)
        session.commit()  # atomic per-question: supersede + new answer + audit
        generated += 1
        _tick()

    if questionnaire.status in (None, "uploaded"):
        questionnaire.status = "in_review"
    session.commit()
    return {
        "generated": generated,
        "skipped": skipped,
        "preserved": preserved,
        "failed": failed,
        "total": total,
    }


# --- review actions ---------------------------------------------------------

def review_answer(
    session: Session,
    *,
    org: Organization,
    answer_id: uuid.UUID,
    action: str,
    edited_text: str | None = None,
    comment: str | None = None,
    reviewer: str | None = None,
) -> Answer:
    """Apply a reviewer action: transition status + write answer_review + audit. Caller
    commits. Raises ``LookupError`` if the answer isn't in this org, ``ValueError`` for
    an unknown action."""
    answer = session.scalar(
        select(Answer).where(Answer.id == answer_id, Answer.org_id == org.id)
    )
    if answer is None:
        raise LookupError("answer not found")
    after = next_review_status(action)  # validates the action first
    before = answer.review_status

    if action == "edit" and edited_text:
        answer.answer_text = edited_text
        answer.short_answer = edited_text[:512]
    answer.review_status = after
    # A human approving/saving has reviewed it; reject/needs-evidence stays flagged.
    if after == "approved":
        answer.needs_human_review = False

    session.add(
        AnswerReview(
            org_id=org.id,
            answer_id=answer.id,
            reviewer=reviewer,
            action=action,
            edited_text=edited_text,
            comment=comment,
        )
    )
    if action == "save_to_library":
        _save_to_library(session, org, answer)
    session.add(
        AuditLog(
            org_id=org.id,
            actor=reviewer or "system:review",
            action="answer.review",
            target_type="answer",
            target_id=answer.id,
            # Labels only — no answer text, no evidence content.
            payload={"action": action, "before_status": before, "after_status": after},
        )
    )
    session.flush()
    return answer


def _save_to_library(session: Session, org: Organization, answer: Answer) -> None:
    """Create an approved_answer *candidate* from a reviewed answer (principle 7).

    It is a reuse candidate — re-validated against current evidence on future retrieval,
    never an authoritative bypass. It is not re-embedded here; that happens on reseed.
    """
    question = session.get(Question, answer.question_id)
    session.add(
        ApprovedAnswer(
            org_id=org.id,
            source="review",
            question_external_id=question.external_id if question else None,
            domain=question.domain if question else None,
            question_text=question.text if question else (answer.claim or ""),
            answer_text=answer.short_answer,
            answer_detail=answer.answer_text,
            extra={"from_answer_id": str(answer.id), "candidate": True},
        )
    )


# --- document access --------------------------------------------------------

def prepare_document_download(
    session: Session,
    *,
    org: Organization,
    document_id: uuid.UUID,
    client_ip: str | None = None,
    actor: str = "user:download",
) -> tuple[Evidence, str]:
    """Authorize a document download and record the access; caller streams + commits.

    Defense in depth (05 §8): every check is org-scoped and **fails closed to 404** — a
    document that belongs to another org, isn't customer-shareable, or isn't referenced by
    an approved answer is indistinguishable from one that doesn't exist (no existence leak,
    default deny). On success we write a ``document.download`` audit row carrying metadata
    only (who/org, document id, ip, timestamp) — never the document bytes.
    """
    evidence = session.scalar(
        select(Evidence).where(Evidence.id == document_id, Evidence.org_id == org.id)
    )
    if evidence is None or not evidence.customer_shareable:
        raise LookupError("document not found")

    # The document must be referenced by an APPROVED answer (a human signed off on
    # providing it) — being shareable alone is not enough to expose the bytes.
    referenced = session.scalar(
        select(Answer.id)
        .where(
            Answer.org_id == org.id,
            Answer.review_status == "approved",
            Answer.provided_documents.contains([{"document_id": str(document_id)}]),
        )
        .limit(1)
    )
    if referenced is None:
        raise LookupError("document not found")

    session.add(
        AuditLog(
            org_id=org.id,
            actor=actor,
            action="document.download",
            target_type="document",
            target_id=evidence.id,
            payload={"document_id": str(evidence.id), "ip": client_ip},
        )
    )
    return evidence, object_key_from_storage_path(evidence.storage_path)


def attach_documents(
    session: Session,
    *,
    org: Organization,
    answer_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    actor: str = "user:review",
) -> Answer:
    """Attach analyst-selected documents to a generic document-request answer (05 §8); caller
    commits.

    Every selection is resolved server-side and fails closed: each id must be a real,
    org-owned, **customer_shareable** Evidence record — anything that doesn't resolve, is
    cross-org, or isn't shareable is rejected (nothing is attached). On success the answer's
    ``provided_documents`` is set (plus any remediation the chosen docs carry), the
    ``document_selection_required`` flag is cleared, and a ``document.attach`` audit row
    (metadata only) is written.
    """
    answer = session.scalar(
        select(Answer).where(Answer.id == answer_id, Answer.org_id == org.id)
    )
    if answer is None:
        raise LookupError("answer not found")
    if not document_ids:
        raise ValueError("no documents selected")

    # Resolve strictly: org-scoped + customer_shareable. A requested id that doesn't resolve
    # to a shareable record (cross-org, non-shareable, or unknown) rejects the whole request.
    unique_ids = list(dict.fromkeys(document_ids))
    docs = session.scalars(
        select(Evidence).where(
            Evidence.org_id == org.id,
            Evidence.id.in_(unique_ids),
            Evidence.customer_shareable.is_(True),
        )
    ).all()
    by_id = {d.id: d for d in docs}
    if len(by_id) != len(unique_ids):
        raise ValueError("one or more selected documents are not available to attach")

    ordered = [by_id[i] for i in unique_ids]
    answer.provided_documents = [
        {"document_id": str(d.id), "title": d.title} for d in ordered
    ]
    # Render any remediation the chosen documents carry (org-scoped, shareable findings).
    findings = session.scalars(
        select(Finding).where(
            Finding.org_id == org.id,
            Finding.source_document_id.in_([d.id for d in ordered]),
            Finding.customer_shareable.is_(True),
        )
    ).all()
    answer.finding_refs = [str(f.id) for f in findings]
    answer.remediation_required = bool(findings)
    answer.document_selection_required = False

    session.add(
        AuditLog(
            org_id=org.id,
            actor=actor,
            action="document.attach",
            target_type="answer",
            target_id=answer.id,
            # Metadata only — the document ids selected + count, never document content.
            payload={
                "answer_id": str(answer.id),
                "document_ids": [str(d.id) for d in ordered],
                "count": len(ordered),
            },
        )
    )
    return answer


# --- export -----------------------------------------------------------------

def _export_rows(
    session: Session, org: Organization, questionnaire_id: uuid.UUID
) -> list[dict]:
    detail = get_questionnaire_detail(
        session, org=org, questionnaire_id=questionnaire_id
    )
    if detail is None:
        raise LookupError("questionnaire not found")
    latest = _latest_answers(session, org, questionnaire_id)
    # Latest reviewer per answer, in one query.
    answer_ids = [a.id for a in latest.values()]
    reviewer_by_answer: dict[uuid.UUID, str] = {}
    if answer_ids:
        reviews = session.scalars(
            select(AnswerReview)
            .where(AnswerReview.answer_id.in_(answer_ids), AnswerReview.org_id == org.id)
            .order_by(AnswerReview.created_at.asc())
        ).all()
        for r in reviews:
            if r.reviewer:
                reviewer_by_answer[r.answer_id] = r.reviewer

    rows: list[dict] = []
    for q in detail["questions"]:
        answer = latest.get(uuid.UUID(q["id"]))
        evidence = ""
        documents = ""
        remediation = ""
        if answer and answer.evidence_refs:
            evidence = "; ".join(
                str(ref.get("title") or ref.get("source_type") or "")
                for ref in answer.evidence_refs
            )
        if answer:
            documents = "; ".join(
                str(d.get("title") or d.get("document_id") or "")
                for d in (answer.provided_documents or [])
                if isinstance(d, dict)
            )
            if answer.remediation_required:
                remediation = _remediation_text(
                    _render_findings(session, org, answer.finding_refs)
                )
        rows.append(
            {
                "id": q["external_id"] or "",
                "domain": q["domain"] or "",
                "question": q["text"],
                "outcome": (answer.outcome if answer else "") or "",
                "review_status": (answer.review_status if answer else "undrafted"),
                "needs_human_review": (
                    "" if answer is None else str(bool(answer.needs_human_review)).lower()
                ),
                "confidence": (answer.confidence if answer else "") or "",
                "short_answer": (answer.short_answer if answer else "") or "",
                "answer": (answer.answer_text if answer else "") or "",
                "documents": documents,
                "remediation": remediation,
                "evidence": evidence,
                "freshness": (answer.freshness_status if answer else "") or "",
                "reviewer": reviewer_by_answer.get(answer.id, "") if answer else "",
            }
        )
    return rows


def _remediation_text(findings: list[dict]) -> str:
    """Compact, customer-facing remediation status line for an export cell (no owner)."""
    parts = []
    for f in findings:
        ref = f.get("external_ref") or "finding"
        bits = [str(ref)]
        if f.get("severity"):
            bits.append(str(f["severity"]))
        if f.get("status"):
            bits.append(str(f["status"]).replace("_", " "))
        if f.get("status") in ("open", "in_progress") and f.get("target_remediation_date"):
            bits.append(f"target {f['target_remediation_date']}")
        elif f.get("remediated_date"):
            bits.append(f"remediated {f['remediated_date']}")
        parts.append(" — ".join(bits))
    return "; ".join(parts)


def rows_to_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens UTF-8 cleanly


def rows_to_xlsx(rows: list[dict]) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Answers"
    ws.append(EXPORT_COLUMNS)
    for row in rows:
        ws.append([row.get(col, "") for col in EXPORT_COLUMNS])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


_EXPORT_FORMATS = {
    "csv": ("text/csv", rows_to_csv),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        rows_to_xlsx,
    ),
}


def export_answers(
    session: Session, *, org: Organization, questionnaire_id: uuid.UUID, fmt: str
) -> tuple[bytes, str, str]:
    """Return ``(body, media_type, filename)`` for the reviewed answers.

    The export carries ``review_status`` / ``needs_human_review`` on every row, so
    nothing reads as final that a human did not approve (principle 2)."""
    if fmt not in _EXPORT_FORMATS:
        raise ValueError(f"unsupported export format: {fmt!r}")
    media_type, serialize = _EXPORT_FORMATS[fmt]
    rows = _export_rows(session, org, questionnaire_id)
    filename = f"trustbot-answers-{questionnaire_id}.{fmt}"
    return serialize(rows), media_type, filename
