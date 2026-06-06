"""TrustBot API.

Phase 0 added /health. Phase 1 adds the data layer + a read-only /debug/summary
that surfaces what the seed loaded. Later phases add ingestion, retrieval, answer
generation, and the review workspace.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .answers import generate_answer, persist_answer
from .config import settings
from .db import SessionLocal, check_db, get_session
from .db.models import (
    ApprovedAnswer,
    CompanyProfile,
    Control,
    Evidence,
    EvidenceControlLink,
    KnowledgeChunk,
    Organization,
    Question,
    Questionnaire,
)
from .questionnaires.jobs import fail_orphaned_jobs
from .retrieval import RetrievalFilters, retrieve
from .review_routes import router as review_router

logger = logging.getLogger("trustbot")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # In-process generation jobs die with the process, so on startup mark any job left
    # pending/running by a prior process as failed — a dead job never shows as
    # forever-running. Best-effort: never block startup on it.
    try:
        with SessionLocal() as session:
            n = fail_orphaned_jobs(session)
            session.commit()
            if n:
                logger.info("startup: failed %d orphaned generation job(s)", n)
    except Exception as exc:  # noqa: BLE001 - best-effort; generic only, never a secret
        logger.warning("startup: orphaned-job cleanup skipped (%s)", type(exc).__name__)
    yield


app = FastAPI(title="TrustBot API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Phase 5 review workspace (intake, drafting, review actions, export).
app.include_router(review_router)


def require_debug_enabled() -> None:
    """Hide debug/introspection endpoints outside non-production environments.

    Resolved before the DB session, so a disabled endpoint never touches the
    database. Returns 404 (not 403) so the route's existence isn't disclosed.
    """
    if not settings.debug_endpoints_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


@app.get("/health")
def health() -> dict:
    db_ok = check_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "trustbot-api",
        "env": settings.app_env,
        "database": "connected" if db_ok else "unavailable",
    }


@app.get("/debug/summary", dependencies=[Depends(require_debug_enabled)])
def debug_summary(session: Session = Depends(get_session)) -> dict:
    """Read-only snapshot of the seeded demo org. Counts only — no secrets.

    Gated to non-production environments (see require_debug_enabled). Single-tenant
    demo: returns the first org. (Multi-tenant access control is a roadmap item;
    this endpoint would become org-scoped and authenticated.)
    """
    org = session.scalar(select(Organization).limit(1))
    if org is None:
        return {"seeded": False}

    def count(model) -> int:
        return session.scalar(
            select(func.count()).select_from(model).where(model.org_id == org.id)
        )

    profile = session.scalar(
        select(CompanyProfile).where(CompanyProfile.org_id == org.id).limit(1)
    )
    # Policies are stored as Evidence rows (evidence_type='policy'); count them
    # separately so 'evidence' stays the attestation-document count.
    policy_count = session.scalar(
        select(func.count())
        .select_from(Evidence)
        .where(Evidence.org_id == org.id, Evidence.evidence_type == "policy")
    )
    return {
        "seeded": True,
        "org": {"id": str(org.id), "name": org.name, "slug": org.slug},
        "profile_present": profile is not None,
        "counts": {
            "controls": count(Control),
            "evidence": count(Evidence) - policy_count,
            "policies": policy_count,
            "evidence_control_links": count(EvidenceControlLink),
            "approved_answers": count(ApprovedAnswer),
            "knowledge_chunks": count(KnowledgeChunk),
            "questionnaires": count(Questionnaire),
            "questions": count(Question),
        },
    }


class RetrieveRequest(BaseModel):
    """All fields validated/bounded at the boundary (untrusted input)."""

    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    # Optional metadata filters. customer_shareable=True restricts to chunks
    # marked externally shareable — the same gate Phase 4 uses for customer answers.
    source_types: list[str] | None = Field(default=None, max_length=16)
    confidentiality: list[str] | None = Field(default=None, max_length=16)
    customer_shareable: bool | None = None


@app.post("/retrieve", dependencies=[Depends(require_debug_enabled)])
def retrieve_chunks(
    req: RetrieveRequest, session: Session = Depends(get_session)
) -> dict:
    """Rank knowledge chunks for an arbitrary question (hybrid + rerank).

    A tuning/demo endpoint that returns chunk *text*, so it's gated to non-production
    like /debug/summary (see require_debug_enabled). Single-tenant demo: scopes to the
    first org. Multi-tenant access control is a roadmap item.
    """
    org = session.scalar(select(Organization).limit(1))
    if org is None:
        return {"seeded": False, "results": []}

    filters = RetrievalFilters(
        org_id=org.id,
        source_types=req.source_types,
        confidentiality=req.confidentiality,
        customer_shareable=req.customer_shareable,
    )
    results = retrieve(session, query=req.question, filters=filters, top_k=req.top_k)
    return {
        "org": {"id": str(org.id), "slug": org.slug},
        "question": req.question,
        "count": len(results),
        "results": [
            {
                "chunk_id": str(r.chunk_id),
                "source_type": r.source_type,
                "source_id": str(r.source_id) if r.source_id else None,
                "fusion_score": round(r.fusion_score, 6),
                "rerank_score": round(r.rerank_score, 6),
                "meta": r.meta,
                "text": r.chunk_text,
            }
            for r in results
        ],
    }


class AnswerRequest(BaseModel):
    """Bounded/validated at the boundary (untrusted input)."""

    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    persist: bool = True


@app.post("/answer", dependencies=[Depends(require_debug_enabled)])
def answer_question(
    req: AnswerRequest, session: Session = Depends(get_session)
) -> dict:
    """Draft an evidence-grounded answer for a question (fixed retrieve-then-answer).

    Returns answer text, so it's gated to non-production like /retrieve. Single-tenant
    demo: scopes to the first org. The draft is never auto-emitted — ``needs_human_review``
    governs Phase 5 review; nothing here is customer-facing without human sign-off.
    """
    org = session.scalar(select(Organization).limit(1))
    if org is None:
        return {"seeded": False}

    ga = generate_answer(session, org=org, question=req.question, top_k=req.top_k)
    answer_id: str | None = None
    if req.persist:
        answer = persist_answer(session, org=org, ga=ga)
        session.commit()
        answer_id = str(answer.id)

    return {
        "org": {"id": str(org.id), "slug": org.slug},
        "answer_id": answer_id,
        **ga.model_dump(mode="json"),
    }
