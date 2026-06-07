"""Seed produces the pentest remediation register (§9/§13) — DB-backed.

Uses the shared ``pg_session`` fixture (skips without TEST_DATABASE_URL, rolls back). Calls
``_seed_findings`` directly so it needs no full seed run, storage, or models.
"""
import uuid
from datetime import date

from sqlalchemy import select

from app.db.models import Evidence, Finding, Organization
from app.seed import _seed_findings


def _org_with_pentest(session) -> tuple[Organization, Evidence]:
    org = Organization(name="Findings Test", slug=f"findings-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    pentest = Evidence(
        org_id=org.id,
        title="Pentest Executive Summary",
        evidence_type="pentest_summary",
        original_filename="p.md",
        storage_path="x",
        file_hash="h",
        confidentiality="confidential",
        customer_shareable=True,
        status="active",
    )
    session.add(pentest)
    session.flush()
    return org, pentest


def test_seed_findings_creates_org_scoped_register(pg_session):
    org, pentest = _org_with_pentest(pg_session)

    n = _seed_findings(pg_session, org, [(pentest, b"")])
    assert n == 5

    findings = pg_session.scalars(
        select(Finding).where(Finding.org_id == org.id)
    ).all()
    assert len(findings) == 5
    # All org-scoped, linked to the pentest, typed pentest.
    assert all(f.org_id == org.id for f in findings)
    assert all(f.source_document_id == pentest.id for f in findings)
    assert all(f.source_type == "pentest" for f in findings)


def test_seed_findings_open_high_idor_has_a_target_date(pg_session):
    org, pentest = _org_with_pentest(pg_session)
    _seed_findings(pg_session, org, [(pentest, b"")])
    by_ref = {
        f.external_ref: f
        for f in pg_session.scalars(select(Finding).where(Finding.org_id == org.id))
    }

    h01 = by_ref["H-01"]
    assert h01.status == "in_progress"
    assert h01.severity == "High"  # verbatim from the report, not our own scale
    assert h01.identified_date == date(2026, 3, 27)
    assert h01.target_remediation_date == date(2026, 5, 15)  # a plan for the open finding
    assert h01.remediated_date is None
    assert h01.customer_shareable is True
    assert h01.remediation_summary  # a shareable summary is present
    assert h01.owner  # internal-only field present (render filters it, the row keeps it)

    # The rest are closed out — remediated or risk-accepted, none still open.
    closed = [f for f in by_ref.values() if f.external_ref != "H-01"]
    assert {f.status for f in closed} <= {"remediated", "risk_accepted"}
    assert by_ref["L-01"].status == "risk_accepted"


def test_seed_findings_noop_without_pentest(pg_session):
    org = Organization(name="No Pentest", slug=f"nopt-{uuid.uuid4().hex[:8]}")
    pg_session.add(org)
    pg_session.flush()
    assert _seed_findings(pg_session, org, []) == 0
    assert pg_session.scalars(select(Finding).where(Finding.org_id == org.id)).all() == []
