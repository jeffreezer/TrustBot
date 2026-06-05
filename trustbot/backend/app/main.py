"""TrustBot API.

Phase 0 added /health. Phase 1 adds the data layer + a read-only /debug/summary
that surfaces what the seed loaded. Later phases add ingestion, retrieval, answer
generation, and the review workspace.
"""
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import check_db, get_session
from .db.models import (
    ApprovedAnswer,
    CompanyProfile,
    Control,
    Evidence,
    EvidenceControlLink,
    KnowledgeChunk,
    Organization,
)

app = FastAPI(title="TrustBot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    return {
        "seeded": True,
        "org": {"id": str(org.id), "name": org.name, "slug": org.slug},
        "profile_present": profile is not None,
        "counts": {
            "controls": count(Control),
            "evidence": count(Evidence),
            "evidence_control_links": count(EvidenceControlLink),
            "approved_answers": count(ApprovedAnswer),
            "knowledge_chunks": count(KnowledgeChunk),
        },
    }
