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
    _available_certs,
    _freshness,
    _resolve_reused_approvals,
)
from app.answers.schema import CitedEvidence, Claim, ClaimStatus, ClaimType
from app.answers.validate import (
    extract_attested_certifications,
    validate_certification_claims,
)
from app.db.models import ApprovedAnswer, Evidence, Organization


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


# --- held certifications are DERIVED FROM INGESTED EVIDENCE (07 §3.3/§5) -----

# A synthetic ISO certificate/SoA whose OWN TEXT lists the family — extraction reads this, so
# the held set is what the document attests, not a hand-maintained list.
_ISO_DOC = (
    "Certificate of Registration. Standards: ISO/IEC 27001:2022, ISO/IEC 27017:2015, "
    "ISO/IEC 27018:2019, ISO/IEC 27701:2019. Statement of Applicability attached."
)


def _attestation(session, org, *, kind: str, text: str) -> Evidence:
    ev = Evidence(
        org_id=org.id, title=kind, evidence_type=kind, document_kind=kind,
        attested_certifications=extract_attested_certifications(text, kind),
        original_filename=f"{kind}.md", storage_path="", file_hash="0" * 64,
        customer_shareable=True,
    )
    session.add(ev)
    session.flush()
    return ev


def test_available_certs_derives_from_ingested_attestation(pg_session):
    org = _org(pg_session)
    iso = _attestation(pg_session, org, kind="iso_certificate", text=_ISO_DOC)
    # The whole ISO family is extracted from the document's OWN text and recorded on the row.
    assert set(iso.attested_certifications) == {
        "iso 27001", "iso 27017", "iso 27018", "iso 27701"
    }
    held = _available_certs(pg_session, org.id)
    assert {"iso 27001", "iso 27017", "iso 27018", "iso 27701"} <= held
    # Nothing the org never ingested an attestation for is "held".
    assert "fedramp" not in held and "iso 9001" not in held and "soc 1" not in held


def test_removing_attestation_evidence_unholds_its_certs(pg_session):
    # THE decisive test (07 §5): held-status is evidence-derived, not a declared list. With the
    # ISO certificate ingested, ISO is held → an affirmed ISO claim is NOT an overclaim. Remove
    # the document and ISO is no longer held → the SAME affirmation flags. Proof it comes from
    # evidence, not a value typed into a profile.
    org = _org(pg_session)
    iso = _attestation(pg_session, org, kind="iso_certificate", text=_ISO_DOC)
    affirmed_iso = Claim(
        subject="ISO 27017", claim_type=ClaimType.CERTIFICATION, status=ClaimStatus.AFFIRMED
    )

    assert "iso 27017" in _available_certs(pg_session, org.id)
    assert validate_certification_claims([affirmed_iso], _available_certs(pg_session, org.id)) == []

    pg_session.delete(iso)
    pg_session.flush()

    held = _available_certs(pg_session, org.id)
    assert "iso 27017" not in held
    reasons = validate_certification_claims([affirmed_iso], held)
    assert reasons and "ISO 27017" in reasons[0]  # now an overclaim — no attestation covers it


def test_iso_family_held_status_is_per_standard_not_collapsed(pg_session):
    # Regression (07 §3.3/§5): the generic ISO 27xxx recognizer matches the FORMAT of any
    # standard, but held-status is per SPECIFIC standard — never collapsed across the family. A
    # certificate whose own text names ONLY ISO 27001 makes ONLY 27001 held; affirming a sibling
    # it does not list is an overclaim. If the recognizer ever collapsed siblings onto "iso
    # 27001" (one canonical name for the whole family), every 27xxx would blanket-affirm and the
    # org would overclaim certs it doesn't hold — this pins against that.
    org = _org(pg_session)
    iso = _attestation(
        pg_session, org, kind="iso_certificate",
        text="Certificate of Registration. Standards: ISO/IEC 27001:2022.",
    )
    assert set(iso.attested_certifications) == {"iso 27001"}  # ONLY the listed standard
    held = _available_certs(pg_session, org.id)
    assert held == {"iso 27001"}

    def _affirm(subject: str) -> list[str]:
        claim = Claim(
            subject=subject, claim_type=ClaimType.CERTIFICATION, status=ClaimStatus.AFFIRMED
        )
        return validate_certification_claims([claim], held)

    # The held primary is a clean affirmation...
    assert _affirm("ISO 27001") == []
    # ...but siblings the certificate does NOT list are overclaims (family NOT collapsed).
    for sibling in ("ISO 27017", "ISO 27018", "ISO 27701"):
        reasons = _affirm(sibling)
        assert reasons and sibling in reasons[0], f"{sibling} must flag as an overclaim"
