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
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .db.models import Organization
from .deps import get_current_org
from .questionnaires import QuestionnaireParseError, service

router = APIRouter(tags=["review"])


def _to_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"invalid {what} id") from None


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


@router.post("/questionnaires/{questionnaire_id}/generate")
def generate_drafts(
    questionnaire_id: str,
    req: GenerateRequest | None = None,
    session: Session = Depends(get_session),
    org: Organization = Depends(get_current_org),
) -> dict:
    try:
        result = service.generate_drafts(
            session,
            org=org,
            questionnaire_id=_to_uuid(questionnaire_id, "questionnaire"),
            regenerate=(req.regenerate if req else False),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return result


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
