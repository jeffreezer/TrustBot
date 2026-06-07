"""Analyst document selection on a generic request resolves + audits (05 §8).

DB-backed (shared ``pg_session``; skips without TEST_DATABASE_URL). The analyst's choice is
resolved server-side and fails closed: only a real, org-owned, customer_shareable document
attaches; cross-org / non-shareable / unknown selections are rejected and nothing changes.
A ``document.attach`` audit row (metadata only) is written on success.
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
from app.questionnaires.service import attach_documents


def _evidence(org, *, title, kind="document", shareable=True):
    return Evidence(
        org_id=org.id,
        title=title,
        evidence_type=kind,
        document_kind=kind,
        original_filename=f"{title}.md",
        storage_path="x",
        file_hash="h",
        confidentiality="confidential",
        customer_shareable=shareable,
        status="active",
    )


def _org(session, name="Attach Test") -> Organization:
    org = Organization(name=name, slug=f"attach-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    return org


def _answer_awaiting_selection(session, org) -> Answer:
    qn = Questionnaire(org_id=org.id, title="QN", status="ready")
    session.add(qn)
    session.flush()
    q = Question(org_id=org.id, questionnaire_id=qn.id, text="Share relevant documentation.")
    session.add(q)
    session.flush()
    ans = Answer(
        org_id=org.id,
        question_id=q.id,
        outcome="attested",
        mode="respond",
        requires_document=True,
        document_selection_required=True,
        needs_human_review=True,
        review_status="pending",
    )
    session.add(ans)
    session.flush()
    return ans


def test_attach_selected_document_resolves_clears_flag_and_audits(pg_session):
    org = _org(pg_session)
    ans = _answer_awaiting_selection(pg_session, org)
    doc = _evidence(org, title="Security Whitepaper", kind="whitepaper")
    pg_session.add(doc)
    pg_session.flush()

    updated = attach_documents(
        pg_session, org=org, answer_id=ans.id, document_ids=[doc.id]
    )
    assert updated.document_selection_required is False
    assert updated.provided_documents == [
        {"document_id": str(doc.id), "title": "Security Whitepaper"}
    ]
    audit = pg_session.scalar(
        select(AuditLog).where(
            AuditLog.org_id == org.id,
            AuditLog.action == "document.attach",
            AuditLog.target_id == ans.id,
        )
    )
    assert audit is not None
    assert audit.payload["count"] == 1
    assert audit.payload["document_ids"] == [str(doc.id)]


def test_attach_swaps_to_a_different_shareable_document(pg_session):
    # The analyst deselects the recommended doc and confirms a different shareable artifact.
    org = _org(pg_session)
    ans = _answer_awaiting_selection(pg_session, org)
    recommended = _evidence(org, title="HR Security Policy", kind="policy")
    chosen = _evidence(org, title="Information Security Policy", kind="policy")
    pg_session.add_all([recommended, chosen])
    pg_session.flush()

    updated = attach_documents(
        pg_session, org=org, answer_id=ans.id, document_ids=[chosen.id]
    )
    assert [d["title"] for d in updated.provided_documents] == ["Information Security Policy"]
    assert updated.document_selection_required is False


def test_attach_populates_remediation_when_doc_has_findings(pg_session):
    from app.db.models import Finding

    org = _org(pg_session)
    ans = _answer_awaiting_selection(pg_session, org)
    pentest = _evidence(org, title="Pentest Summary", kind="pentest_report")
    pg_session.add(pentest)
    pg_session.flush()
    pg_session.add(
        Finding(
            org_id=org.id,
            source_document_id=pentest.id,
            source_type="pentest",
            external_ref="H-01",
            title="Open finding",
            status="in_progress",
            customer_shareable=True,
        )
    )
    pg_session.flush()

    updated = attach_documents(pg_session, org=org, answer_id=ans.id, document_ids=[pentest.id])
    assert updated.remediation_required is True
    assert len(updated.finding_refs) == 1


def test_attach_rejects_non_shareable_document(pg_session):
    org = _org(pg_session)
    ans = _answer_awaiting_selection(pg_session, org)
    internal = _evidence(org, title="Internal Runbook", shareable=False)
    pg_session.add(internal)
    pg_session.flush()

    with pytest.raises(ValueError):
        attach_documents(pg_session, org=org, answer_id=ans.id, document_ids=[internal.id])
    pg_session.refresh(ans)
    assert ans.document_selection_required is True  # nothing changed
    assert ans.provided_documents == []


def test_attach_rejects_cross_org_document(pg_session):
    org = _org(pg_session)
    other = _org(pg_session, "Other Co")
    ans = _answer_awaiting_selection(pg_session, org)
    foreign = _evidence(other, title="Other SOC 2", kind="soc2_report")
    pg_session.add(foreign)
    pg_session.flush()

    with pytest.raises(ValueError):
        attach_documents(pg_session, org=org, answer_id=ans.id, document_ids=[foreign.id])


def test_attach_unknown_answer_raises_lookup(pg_session):
    org = _org(pg_session)
    with pytest.raises(LookupError):
        attach_documents(
            pg_session, org=org, answer_id=uuid.uuid4(), document_ids=[uuid.uuid4()]
        )
