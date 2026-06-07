"""Respond-mode validators — downgrade gates + review flags, each fails closed."""
from app.answers.schema import AnswerDraft, CitedEvidence, RespondOutcome
from app.answers.validate import (
    FindingStatus,
    asserted_certifications,
    controlling_gate,
    open_findings_gate,
    run_review_checks,
    validate_certifications,
    validate_citations,
    validate_required_fields,
    validate_shareability,
)


def _draft(**kw):
    base = dict(outcome=RespondOutcome.ATTESTED, short_answer="Yes.", claim="c", answer="a")
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


def test_affirmative_with_no_citation_is_rejected():
    reasons = validate_citations(_draft(evidence_refs=[]), grounding_refs=["a"])
    assert reasons


def test_valid_subset_of_grounding_passes():
    assert validate_citations(_draft(evidence_refs=["a"]), grounding_refs=["a", "b"]) == []


# --- controlling gate (anti-fabrication; failure => needs_input) ------------

def test_attested_without_controlling_source_is_downgraded():
    # Only a reused approved answer / marketing profile — not controlling.
    cited = [_cite("a", source_type="approved_answer"), _cite("b", source_type="company_profile")]
    assert controlling_gate(_draft(), cited) is not None


def test_attested_with_policy_passes_gate():
    assert controlling_gate(_draft(), [_cite("a", source_type="policy")]) is None


def test_qualified_with_control_passes_gate():
    cited = [_cite("a", source_type="control")]
    assert controlling_gate(_draft(outcome=RespondOutcome.QUALIFIED), cited) is None


def test_negative_outcome_skips_controlling_gate():
    assert controlling_gate(_draft(outcome=RespondOutcome.NEGATIVE), []) is None


# --- open-finding gate (failure => needs_input) -----------------------------

def test_open_finding_without_target_date_is_downgraded():
    findings = [FindingStatus("id1", "H-01", "in_progress", has_target_date=False)]
    reason = open_findings_gate(True, findings)
    assert reason and "H-01" in reason


def test_open_finding_with_target_date_passes():
    findings = [FindingStatus("id1", "H-01", "in_progress", has_target_date=True)]
    assert open_findings_gate(True, findings) is None


def test_remediated_finding_without_date_is_fine():
    findings = [FindingStatus("id1", "M-01", "remediated", has_target_date=False)]
    assert open_findings_gate(True, findings) is None


def test_no_remediation_required_skips_gate():
    findings = [FindingStatus("id1", "H-01", "open", has_target_date=False)]
    assert open_findings_gate(False, findings) is None


# --- certifications ---------------------------------------------------------

def test_cert_claimed_without_evidence_is_rejected():
    draft = _draft(claim="We are SOC 1 certified.", answer="SOC 1 certified.")
    reasons = validate_certifications(draft, available_certs={"soc 2", "iso 27001"})
    assert reasons and "soc 1" in reasons[0]


def test_cert_claimed_with_evidence_passes():
    draft = _draft(claim="We hold SOC 2.", answer="SOC 2 Type 2.")
    assert validate_certifications(draft, available_certs={"soc 2"}) == []


def test_needs_input_outcome_skips_cert_check():
    draft = _draft(outcome=RespondOutcome.NEEDS_INPUT, short_answer="", claim="", answer="FedRAMP")
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

def test_required_fields_for_drafted_outcome():
    assert validate_required_fields(_draft(claim="")) != []
    assert validate_required_fields(_draft()) == []


def test_run_review_checks_aggregates_failures():
    draft = _draft(claim="We are SOC 1 certified.", evidence_refs=["ghost"])
    reasons = run_review_checks(
        draft,
        [_cite("a", shareable=False)],
        grounding_refs=["a"],
        available_certs={"soc 2"},
        customer_facing=True,
    )
    # citation + cert + shareability all fire.
    assert len(reasons) >= 3
