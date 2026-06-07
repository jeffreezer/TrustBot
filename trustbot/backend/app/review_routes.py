"""Phase 5 review-workspace API: intake, drafting, review actions, export.

Unlike the debug endpoints (/retrieve, /answer, /debug/summary), these are the product
surface, so they are not gated to non-production — they are **org-scoped** instead (via
``get_current_org``) and would be authenticated once real auth lands. Every request body
is bounded/validated with Pydantic; the file upload is size-checked at the boundary and
the bytes are treated as data, never executed.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .db.models import GenerationJob, Organization
from .deps import get_current_org
from .questionnaires import QuestionnaireParseError, jobs, service
from .storage import get_storage, sanitize_filename

router = APIRouter(tags=["review"])


def _to_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"invalid {what} id") from None


def _client_ip(request: Request) -> str | None:
    """The direct peer address for the audit trail. X-Forwarded-For is intentionally NOT
    trusted (a client can spoof it); the proxy hop is acceptable for an access record."""
    return request.client.host if request.client else None


@router.post("/questionnaires")
async def upload_questionnaire(
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> dict:
    """Upload a questionnaire (CSV/Excel) as the raw request body; parse rows → questions.

    Raw-body upload (filename via query) avoids a multipart dependency. Type and size are
    validated here; PDF/unknown types and oversized files are rejected at the boundary.
    """
    max_bytes = settings.max_ingest_bytes
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_bytes:
        raise HTTPException(status_code=413, detail="file too large")
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="file too large")

    try:
        questionnaire = service.create_questionnaire(
            session,
            org=org,
            data=data,
            filename=filename,
            content_type=request.headers.get("content-type"),
        )
    except QuestionnaireParseError as exc:
        # Unsupported type / unparseable / empty — a client error, fail closed.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return {
        "id": str(questionnaire.id),
        "title": questionnaire.title,
        "status": questionnaire.status,
    }


@router.get("/questionnaires")
def list_questionnaires(
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> dict:
    return {"questionnaires": service.list_questionnaires(session, org=org)}


@router.get("/questionnaires/{questionnaire_id}")
def get_questionnaire(
    questionnaire_id: str,
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> dict:
    detail = service.get_questionnaire_detail(
        session, org=org, questionnaire_id=_to_uuid(questionnaire_id, "questionnaire")
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="questionnaire not found")
    return detail


class GenerateRequest(BaseModel):
    regenerate: bool = False


@router.post("/questionnaires/{questionnaire_id}/generate", status_code=202)
async def start_generation(
    questionnaire_id: str,
    req: GenerateRequest | None = None,
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> dict:
    """Start a background draft-generation job and return its id immediately (202).

    Drafting runs in-process off the event loop, committing per answer; poll
    ``GET /jobs/{job_id}`` for live N/total progress. Rejects a second concurrent job for
    the same questionnaire (409) and a questionnaire over MAX_GENERATION_BATCH (422)."""
    regenerate = req.regenerate if req else False
    try:
        job = jobs.create_generation_job(
            session, org=org, questionnaire_id=_to_uuid(questionnaire_id, "questionnaire")
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except jobs.BatchTooLargeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except jobs.ConcurrentJobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job_id = job.id
    session.commit()
    jobs.schedule_job(job_id, regenerate=regenerate)
    return {"job_id": str(job_id)}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> dict:
    """Poll a generation job's progress. Org-scoped: a job from another org returns 404
    (default deny — don't disclose its existence)."""
    job = session.scalar(
        select(GenerationJob).where(
            GenerationJob.id == _to_uuid(job_id, "job"),
            GenerationJob.org_id == org.id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "job_id": str(job.id),
        "status": job.status,
        "total": job.total,
        "completed": job.completed,
        "error": job.error,
    }


@router.get("/questions/{question_id}")
def get_question(
    question_id: str,
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> dict:
    detail = service.get_question_detail(
        session, org=org, question_id=_to_uuid(question_id, "question")
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="question not found")
    return detail


class ReviewRequest(BaseModel):
    action: Literal["approve", "edit", "reject", "request_evidence", "save_to_library"]
    edited_text: str | None = Field(default=None, max_length=20000)
    comment: str | None = Field(default=None, max_length=4000)
    reviewer: str | None = Field(default=None, max_length=255)


@router.post("/answers/{answer_id}/review")
def review_answer(
    answer_id: str,
    req: ReviewRequest,
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> dict:
    try:
        answer = service.review_answer(
            session,
            org=org,
            answer_id=_to_uuid(answer_id, "answer"),
            action=req.action,
            edited_text=req.edited_text,
            comment=req.comment,
            reviewer=req.reviewer,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return {
        "answer_id": str(answer.id),
        "review_status": answer.review_status,
        "needs_human_review": answer.needs_human_review,
    }


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: str,
    request: Request,
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> StreamingResponse:
    """Stream a customer-shareable document referenced by an approved answer (05 §8).

    Org-scoped and fail-closed: a document from another org, one that isn't shareable, or
    one not yet referenced by an approved answer all return 404 (default deny — never a
    bearer/signed link, never an existence leak). The access is audited (metadata only)
    before the bytes are streamed.
    """
    try:
        evidence, key = service.prepare_document_download(
            session,
            org=org,
            document_id=_to_uuid(document_id, "document"),
            client_ip=_client_ip(request),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="document not found") from exc
    session.commit()  # persist the audit record before serving any bytes

    stream = get_storage().get_object_stream(key)
    filename = sanitize_filename(evidence.original_filename or "document")
    return StreamingResponse(
        stream,
        media_type=evidence.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/questionnaires/{questionnaire_id}/export")
def export_questionnaire(
    questionnaire_id: str,
    fmt: Literal["csv", "xlsx"] = Query(default="csv", alias="format"),
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> Response:
    try:
        body, media_type, filename = service.export_answers(
            session,
            org=org,
            questionnaire_id=_to_uuid(questionnaire_id, "questionnaire"),
            fmt=fmt,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
