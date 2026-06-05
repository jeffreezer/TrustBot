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
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..answers import detect_injection, generate_answer, persist_answer
from ..db.models import (
    Answer,
    AnswerReview,
    ApprovedAnswer,
    AuditLog,
    KnowledgeChunk,
    Organization,
    Question,
    Questionnaire,
)
from ..providers import GenerationProvider
from ..storage import get_storage, sanitize_filename
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

EXPORT_COLUMNS = [
    "id", "domain", "question", "outcome", "review_status", "needs_human_review",
    "confidence", "short_answer", "answer", "exceptions", "evidence", "freshness",
    "reviewer",
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
    """Latest answer per question for a questionnaire (a question may be regenerated)."""
    answers = session.scalars(
        select(Answer)
        .join(Question, Answer.question_id == Question.id)
        .where(
            Question.questionnaire_id == questionnaire_id,
            Answer.org_id == org.id,
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
        "questions": [_question_row(q, latest.get(q.id)) for q in questions],
    }


def _answer_payload(answer: Answer) -> dict:
    return {
        "id": str(answer.id),
        "outcome": answer.outcome,
        "short_answer": answer.short_answer,
        "answer": answer.answer_text,
        "claim": answer.claim,
        "scope": answer.scope,
        "exceptions": answer.exceptions,
        "confidence": answer.confidence,
        "needs_human_review": answer.needs_human_review,
        "review_reason": answer.review_reason,
        "review_status": answer.review_status,
        "freshness_status": answer.freshness_status,
        "evidence_refs": answer.evidence_refs or [],
        "generated_by": answer.generated_by,
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
        .where(Answer.question_id == question.id, Answer.org_id == org.id)
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
        "answer": _answer_payload(answer) if answer else None,
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
) -> dict:
    """Generate a Phase-4 draft for each question (skipping already-drafted ones unless
    ``regenerate``). Returns counts. Caller commits."""
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
    latest = _latest_answers(session, org, questionnaire.id)

    generated = 0
    skipped = 0
    for q in questions:
        if not regenerate and q.id in latest:
            skipped += 1
            continue
        ga = generate_answer(session, org=org, question=q.text, generator=generator)
        persist_answer(session, org=org, ga=ga, question=q)
        generated += 1

    if questionnaire.status in (None, "uploaded"):
        questionnaire.status = "in_review"
    return {"generated": generated, "skipped": skipped, "total": len(questions)}


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
        if answer and answer.evidence_refs:
            evidence = "; ".join(
                str(ref.get("title") or ref.get("source_type") or "")
                for ref in answer.evidence_refs
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
                "exceptions": (answer.exceptions if answer else "") or "",
                "evidence": evidence,
                "freshness": (answer.freshness_status if answer else "") or "",
                "reviewer": reviewer_by_answer.get(answer.id, "") if answer else "",
            }
        )
    return rows


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
