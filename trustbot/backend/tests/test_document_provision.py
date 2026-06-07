"""Document provision: named-artifact auto-attach vs generic deferral (05 §7-§8).

DB-backed (shared ``pg_session``; skips without TEST_DATABASE_URL). Exercises kind-based
selection directly (no retrieval/LLM): a NAMED request ("provide your SOC 2 / ISO / PCI")
auto-attaches exactly those attestations and never the whitepaper, while a GENERIC request
("share relevant documentation") attaches nothing and instead surfaces a relevance-ranked,
org-scoped, customer_shareable candidate list for the analyst to choose from.
"""
import uuid
from types import SimpleNamespace

from sqlalchemy import select

import app.answers.generate as gen
from app.answers.generate import _resolve_documents_and_findings, requested_document_kinds
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


def _org(session, name="Provision Test") -> Organization:
    org = Organization(name=name, slug=f"prov-{uuid.uuid4().hex[:8]}")
    session.add(org)
    session.flush()
    return org


def _corpus(session) -> Organization:
    org = _org(session)
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


# --- named-artifact requests (auto-attach; unchanged) -----------------------

def test_request_classifier_picks_named_attestations():
    kinds = requested_document_kinds(
        "Please provide your SOC 2 report, ISO 27001 certificate, and PCI DSS AOC."
    )
    assert kinds == {"soc2_report", "iso_certificate", "pci_aoc"}


def test_named_request_attaches_attestations_not_whitepaper(pg_session):
    org = _corpus(pg_session)
    res = _resolve_documents_and_findings(
        pg_session,
        org.id,
        "Please attach your SOC 2 report, ISO 27001 certificate, and PCI DSS AOC.",
        _doc_request(),
        cited=[],
    )
    titles = {p.title for p in res.provided}
    assert titles == {"SOC 2 Type II", "ISO 27001 Certificate", "PCI DSS AOC"}
    assert "Security Whitepaper" not in titles  # never a stand-in for an attestation
    assert res.missing_kinds == set()
    assert res.selection_required is False  # named request does not need human selection


def test_missing_requested_artifact_is_flagged_not_substituted(pg_session):
    org = _org(pg_session, "No SOC2")
    pg_session.add(_evidence(org, title="Security Whitepaper", kind="whitepaper"))
    pg_session.flush()
    res = _resolve_documents_and_findings(
        pg_session, org.id, "Please share your SOC 2 Type II report.", _doc_request(), cited=[]
    )
    assert res.provided == []
    assert res.missing_kinds == {"soc2_report"}


# --- generic requests (defer + surface candidates) --------------------------

def test_generic_request_defers_and_surfaces_candidates(pg_session, monkeypatch):
    org = _corpus(pg_session)
    # No retrieval ranking → candidates fall back to title order; nothing auto-attached.
    monkeypatch.setattr(gen, "retrieve", lambda *a, **k: [])
    res = _resolve_documents_and_findings(
        pg_session,
        org.id,
        "Please share any relevant documentation you have.",
        _doc_request(),
        cited=[],
    )
    assert res.selection_required is True
    assert res.provided == []  # never auto-attach on an ambiguous request
    titles = {c.title for c in res.candidates}
    assert titles == {
        "SOC 2 Type II",
        "ISO 27001 Certificate",
        "PCI DSS AOC",
        "Security Whitepaper",
    }
    assert all(c.document_kind for c in res.candidates)  # each labeled with its kind


def test_candidates_exclude_non_shareable_and_cross_org(pg_session, monkeypatch):
    org = _corpus(pg_session)
    pg_session.add(_evidence(org, title="Internal Runbook", kind="document", shareable=False))
    other = _org(pg_session, "Other Co")
    pg_session.add(_evidence(other, title="Other SOC 2", kind="soc2_report"))
    pg_session.flush()

    monkeypatch.setattr(gen, "retrieve", lambda *a, **k: [])
    res = _resolve_documents_and_findings(
        pg_session, org.id, "share documentation", _doc_request(), cited=[]
    )
    titles = {c.title for c in res.candidates}
    assert "Internal Runbook" not in titles  # non-shareable never a candidate
    assert "Other SOC 2" not in titles  # cross-org never a candidate
    assert "SOC 2 Type II" in titles


def test_candidates_are_relevance_ranked(pg_session, monkeypatch):
    org = _corpus(pg_session)
    by_title = {
        e.title: e
        for e in pg_session.scalars(
            select(Evidence).where(Evidence.org_id == org.id)
        ).all()
    }
    pci, iso = by_title["PCI DSS AOC"], by_title["ISO 27001 Certificate"]
    # Retrieval ranks PCI first, then ISO; the rest follow (title order).
    monkeypatch.setattr(
        gen,
        "retrieve",
        lambda *a, **k: [
            SimpleNamespace(source_id=pci.id),
            SimpleNamespace(source_id=iso.id),
        ],
    )
    res = _resolve_documents_and_findings(
        pg_session, org.id, "share your compliance docs", _doc_request(), cited=[]
    )
    order = [c.title for c in res.candidates]
    assert order[0] == "PCI DSS AOC"
    assert order[1] == "ISO 27001 Certificate"
