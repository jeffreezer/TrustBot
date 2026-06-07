"""Document-provision attaches the REQUESTED attestation kind, not the grounded doc (05 §7).

DB-backed (shared ``pg_session``; skips without TEST_DATABASE_URL). Exercises the kind-based
selection directly so it needs no retrieval/LLM: builds a corpus with SOC 2 / ISO / PCI
attestations plus a whitepaper, then asserts a "provide your SOC 2 / ISO / PCI" request
attaches exactly the three attestations and never the whitepaper — and that a requested
artifact absent from the corpus is reported as missing (routes to a human, no substitution).
"""
import uuid

from app.answers.generate import (
    _resolve_documents_and_findings,
    requested_document_kinds,
)
from app.answers.schema import AnswerDraft, RespondOutcome
from app.db.models import Evidence, Organization


def _evidence(org, *, title, kind, shareable=True):
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


def _corpus(session) -> Organization:
    org = Organization(name="Provision Test", slug=f"prov-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    session.add_all(
        [
            _evidence(org, title="SOC 2 Type II", kind="soc2_report"),
            _evidence(org, title="ISO 27001 Certificate", kind="iso_certificate"),
            _evidence(org, title="PCI DSS AOC", kind="pci_aoc"),
            _evidence(org, title="Security Whitepaper", kind="whitepaper"),
        ]
    )
    session.flush()
    return org


def _doc_request(**kw):
    base = dict(
        outcome=RespondOutcome.ATTESTED,
        short_answer="Yes.",
        claim="c",
        answer="a",
        requires_document=True,
    )
    base.update(kw)
    return AnswerDraft(**base)


def test_request_classifier_picks_named_attestations():
    kinds = requested_document_kinds(
        "Please provide your SOC 2 report, ISO 27001 certificate, and PCI DSS AOC."
    )
    assert kinds == {"soc2_report", "iso_certificate", "pci_aoc"}


def test_provision_attaches_attestations_not_whitepaper(pg_session):
    org = _corpus(pg_session)
    provided, findings, missing = _resolve_documents_and_findings(
        pg_session,
        org.id,
        "Please attach your SOC 2 report, ISO 27001 certificate, and PCI DSS AOC.",
        _doc_request(),
        cited=[],
    )
    titles = {p.title for p in provided}
    assert titles == {"SOC 2 Type II", "ISO 27001 Certificate", "PCI DSS AOC"}
    assert "Security Whitepaper" not in titles  # never a stand-in for an attestation
    assert missing == set()
    assert findings == []  # these attestations carry no findings register


def test_missing_requested_artifact_is_flagged_not_substituted(pg_session):
    org = Organization(name="No SOC2", slug=f"nosoc2-{uuid.uuid4().hex[:8]}")
    pg_session.add(org)
    pg_session.flush()
    # Only a whitepaper exists — a SOC 2 request must NOT fall back to it.
    pg_session.add(_evidence(org, title="Security Whitepaper", kind="whitepaper"))
    pg_session.flush()

    provided, _findings, missing = _resolve_documents_and_findings(
        pg_session,
        org.id,
        "Please share your SOC 2 Type II report.",
        _doc_request(),
        cited=[],
    )
    assert provided == []
    assert missing == {"soc2_report"}


def test_non_shareable_attestation_is_not_attached(pg_session):
    org = Organization(name="Internal SOC2", slug=f"intsoc2-{uuid.uuid4().hex[:8]}")
    pg_session.add(org)
    pg_session.flush()
    pg_session.add(_evidence(org, title="SOC 2 (internal)", kind="soc2_report", shareable=False))
    pg_session.flush()

    provided, _findings, missing = _resolve_documents_and_findings(
        pg_session, org.id, "Provide your SOC 2 report.", _doc_request(), cited=[]
    )
    assert provided == []
    assert missing == {"soc2_report"}  # exists but not shareable → treat as not available
