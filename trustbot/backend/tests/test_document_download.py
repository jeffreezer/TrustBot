"""Document-download authorization + audit (05 §8) — DB-backed.

Pins the fail-closed access gate: a document is downloadable only when it is org-scoped,
customer_shareable, AND referenced by an approved answer. Every other case raises
LookupError (the route maps that to 404 — default deny, no existence leak). A successful
authorization writes a metadata-only audit row.
"""
import uuid

import pytest
from sqlalchemy import select

from app.db.models import (
    Answer,
    AuditLog,
    Evidence,
    Organization,
    Question,
    Questionnaire,
)
from app.questionnaires.service import prepare_document_download


def _org(session, name="Doc Org") -> Organization:
    org = Organization(name=name, slug=f"doc-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    return org


def _shareable_doc(session, org) -> Evidence:
    ev = Evidence(
        org_id=org.id,
        title="SOC 2 Type II",
        evidence_type="soc2_report",
        original_filename="soc2.pdf",
        storage_path=f"file://org/{org.id}/evidence/{uuid.uuid4()}/soc2.pdf",
        content_type="application/pdf",
        file_hash="h",
        confidentiality="confidential",
        customer_shareable=True,
        status="active",
    )
    session.add(ev)
    session.flush()
    return ev


def _approved_answer_for(session, org, doc, *, status="approved") -> Answer:
    qn = Questionnaire(org_id=org.id, title="Q", status="active")
    session.add(qn)
    session.flush()
    q = Question(org_id=org.id, questionnaire_id=qn.id, text="Provide your SOC 2 report")
    session.add(q)
    session.flush()
    answer = Answer(
        org_id=org.id,
        question_id=q.id,
        outcome="attested",
        mode="respond",
        requires_document=True,
        provided_documents=[{"document_id": str(doc.id), "title": doc.title}],
        review_status=status,
        needs_human_review=False,
    )
    session.add(answer)
    session.flush()
    return answer


def test_download_allowed_when_shareable_and_approved_referenced(pg_session):
    org = _org(pg_session)
    doc = _shareable_doc(pg_session, org)
    _approved_answer_for(pg_session, org, doc)

    evidence, key = prepare_document_download(
        pg_session, org=org, document_id=doc.id, client_ip="203.0.113.5"
    )
    assert evidence.id == doc.id
    assert key == f"org/{org.id}/evidence/{doc.storage_path.rsplit('/', 2)[1]}/soc2.pdf"

    # An audit row was written — metadata only, never the bytes.
    audit = pg_session.scalar(
        select(AuditLog).where(
            AuditLog.org_id == org.id, AuditLog.action == "document.download"
        )
    )
    assert audit is not None
    assert audit.target_id == doc.id
    assert audit.payload.get("ip") == "203.0.113.5"
    assert "content" not in (audit.payload or {})


def test_cross_org_document_is_404(pg_session):
    org_a = _org(pg_session, "A")
    org_b = _org(pg_session, "B")
    doc = _shareable_doc(pg_session, org_a)
    _approved_answer_for(pg_session, org_a, doc)

    # org_b cannot reach org_a's document — indistinguishable from non-existent.
    with pytest.raises(LookupError):
        prepare_document_download(pg_session, org=org_b, document_id=doc.id)


def test_not_shareable_document_is_404(pg_session):
    org = _org(pg_session)
    doc = _shareable_doc(pg_session, org)
    doc.customer_shareable = False
    pg_session.flush()
    _approved_answer_for(pg_session, org, doc)

    with pytest.raises(LookupError):
        prepare_document_download(pg_session, org=org, document_id=doc.id)


def test_not_referenced_by_approved_answer_is_404(pg_session):
    org = _org(pg_session)
    doc = _shareable_doc(pg_session, org)
    # Referenced only by a *pending* answer — not yet human-approved for release.
    _approved_answer_for(pg_session, org, doc, status="pending")

    with pytest.raises(LookupError):
        prepare_document_download(pg_session, org=org, document_id=doc.id)


def test_unknown_document_id_is_404(pg_session):
    org = _org(pg_session)
    with pytest.raises(LookupError):
        prepare_document_download(pg_session, org=org, document_id=uuid.uuid4())
