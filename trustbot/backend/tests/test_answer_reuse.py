"""Reuse of a human-approved answer is a valid, traceable, always-reviewed basis (05).

DB-backed (shared ``pg_session``; skips without TEST_DATABASE_URL). Exercises the
server-side approved-answer resolution + freshness directly (no retrieval/LLM): an
affirmative whose only basis is a prior approved answer stays attested but flags for review
and records provenance; a stale prior approval flags harder.
"""
import uuid
from datetime import date, timedelta

from app.answers.generate import (
    _approved_answer_validated_on,
    _freshness,
    _resolve_reused_approvals,
)
from app.answers.schema import CitedEvidence
from app.db.models import ApprovedAnswer, Organization


def _org(session) -> Organization:
    org = Organization(name="Reuse Test", slug=f"reuse-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    return org


def _approved(session, org, *, qid="ENC-01") -> ApprovedAnswer:
    aa = ApprovedAnswer(
        org_id=org.id,
        source="SECQ",
        question_external_id=qid,
        question_text="Is data encrypted at rest?",
        answer_text="Yes. AES-256 at rest.",
    )
    session.add(aa)
    session.flush()
    return aa


def _cite_approved(aa: ApprovedAnswer) -> CitedEvidence:
    return CitedEvidence(
        chunk_id=str(uuid.uuid4()),
        source_type="approved_answer",
        source_id=str(aa.id),
        title=f"{aa.source} {aa.question_external_id}",
        text="Q: Is data encrypted at rest? A: Yes. AES-256.",
        customer_shareable=True,
        confidentiality="confidential",
        rerank_score=1.0,
        fusion_score=0.03,
    )


def test_reused_approval_resolves_server_side(pg_session):
    org = _org(pg_session)
    aa = _approved(pg_session, org)
    cited = [_cite_approved(aa)]

    resolved = _resolve_reused_approvals(pg_session, org.id, cited)
    assert [a.id for a in resolved] == [aa.id]


def test_unresolvable_approved_ref_is_not_a_basis(pg_session):
    org = _org(pg_session)
    # A cited approved_answer whose source_id matches no record (cross-org / fabricated).
    ghost = CitedEvidence(
        chunk_id=str(uuid.uuid4()),
        source_type="approved_answer",
        source_id=str(uuid.uuid4()),
        title="ghost",
        text="...",
        customer_shareable=True,
        confidentiality="confidential",
        rerank_score=1.0,
        fusion_score=0.03,
    )
    assert _resolve_reused_approvals(pg_session, org.id, [ghost]) == []


def test_recent_approval_is_current_stale_one_flags(pg_session):
    org = _org(pg_session)
    fresh = _approved(pg_session, org, qid="ENC-01")
    assert _freshness(pg_session, org.id, [_cite_approved(fresh)]) == "current"

    stale = _approved(pg_session, org, qid="ENC-02")
    # Backdate the last-validated signal well beyond the staleness window.
    stale.extra = {"last_validated": (date.today() - timedelta(days=900)).isoformat()}
    pg_session.flush()
    assert _approved_answer_validated_on(stale) < date.today() - timedelta(days=365)
    assert _freshness(pg_session, org.id, [_cite_approved(stale)]) == "stale"


def test_cross_org_approval_does_not_resolve(pg_session):
    org_a = _org(pg_session)
    org_b = _org(pg_session)
    aa_b = _approved(pg_session, org_b)
    # Citing org B's approval while scoped to org A must not resolve (tenancy).
    assert _resolve_reused_approvals(pg_session, org_a.id, [_cite_approved(aa_b)]) == []
