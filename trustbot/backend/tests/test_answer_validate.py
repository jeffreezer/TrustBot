"""Deterministic validators — each one fails closed on its specific violation."""
from app.answers.schema import AnswerDraft, CitedEvidence, Outcome
from app.answers.validate import (
    asserted_certifications,
    run_all,
    validate_certifications,
    validate_citations,
    validate_required_fields,
    validate_shareability,
)


def _draft(**kw):
    base = dict(outcome=Outcome.SUPPORTED_YES, short_answer="Yes.", claim="c", answer="a")
    base.update(kw)
    return AnswerDraft(**base)


def _cite(chunk_id, *, shareable=True, source_type="policy"):
    return CitedEvidence(
        chunk_id=chunk_id,
        source_type=source_type,
        source_id="s",
        title=f"title-{chunk_id}",
        text="text",
        customer_shareable=shareable,
        confidentiality="confidential",
        rerank_score=1.0,
        fusion_score=0.03,
    )


# --- citations --------------------------------------------------------------

def test_citation_not_in_grounding_is_rejected():
    draft = _draft(evidence_refs=["a", "ghost"])
    reasons = validate_citations(draft, grounding_refs=["a", "b"])
    assert reasons and "ghost" in reasons[0]


def test_answered_outcome_with_no_citation_is_rejected():
    reasons = validate_citations(_draft(evidence_refs=[]), grounding_refs=["a"])
    assert reasons


def test_valid_subset_of_grounding_passes():
    assert validate_citations(_draft(evidence_refs=["a"]), grounding_refs=["a", "b"]) == []


# --- certifications ---------------------------------------------------------

def test_cert_claimed_without_evidence_is_rejected():
    draft = _draft(claim="We are SOC 1 certified.", answer="SOC 1 certified.")
    reasons = validate_certifications(draft, available_certs={"soc 2", "iso 27001"})
    assert reasons and "soc 1" in reasons[0]


def test_cert_claimed_with_evidence_passes():
    draft = _draft(claim="We hold SOC 2.", answer="SOC 2 Type 2.")
    assert validate_certifications(draft, available_certs={"soc 2"}) == []


def test_unknown_outcome_skips_cert_check():
    draft = _draft(outcome=Outcome.UNKNOWN, short_answer="", claim="", answer="FedRAMP")
    assert validate_certifications(draft, available_certs=set()) == []


def test_asserted_certifications_detects_keywords():
    assert asserted_certifications("We are FedRAMP authorized and SOC 2 compliant.") == {
        "fedramp",
        "soc 2",
    }


# --- shareability -----------------------------------------------------------

def test_internal_only_evidence_in_external_answer_is_rejected():
    cited = [_cite("a"), _cite("b", shareable=False)]
    reasons = validate_shareability(cited, customer_facing=True)
    assert reasons and "title-b" in reasons[0]


def test_all_shareable_passes():
    assert validate_shareability([_cite("a"), _cite("b")], customer_facing=True) == []


def test_internal_facing_answer_allows_internal_evidence():
    assert validate_shareability([_cite("b", shareable=False)], customer_facing=False) == []


# --- required fields + aggregate -------------------------------------------

def test_required_fields_for_answered_outcome():
    assert validate_required_fields(_draft(claim="")) != []
    assert validate_required_fields(_draft()) == []


def test_run_all_aggregates_failures():
    draft = _draft(claim="We are SOC 1 certified.", evidence_refs=["ghost"])
    reasons = run_all(
        draft,
        [_cite("a", shareable=False)],
        grounding_refs=["a"],
        available_certs={"soc 2"},
        customer_facing=True,
    )
    # citation + cert + shareability all fire.
    assert len(reasons) >= 3
