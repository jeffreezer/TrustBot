"""Respond-mode validators — downgrade gates + review flags, each fails closed."""
from app.answers.schema import (
    AnswerDraft,
    CitedEvidence,
    Claim,
    ClaimStatus,
    ClaimType,
    RespondOutcome,
)
from app.answers.validate import (
    FindingStatus,
    acceptable_basis_gate,
    asserted_certifications,
    derive_cert_outcome,
    extract_attested_certifications,
    normalize_cert,
    open_findings_gate,
    run_review_checks,
    validate_certification_claims,
    validate_citations,
    validate_required_fields,
    validate_shareability,
)


def _claim(subject, status, *, claim_type=ClaimType.CERTIFICATION, basis=None):
    return Claim(
        subject=subject,
        claim_type=claim_type,
        status=ClaimStatus(status),
        basis=list(basis or []),
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


# --- acceptable-basis gate (anti-fabrication; failure => needs_input) -------

def test_attested_with_company_profile_only_is_downgraded():
    # Marketing copy alone is not a basis; the model's own assertion never counts.
    cited = [_cite("a", source_type="company_profile")]
    assert acceptable_basis_gate(_draft(), cited) is not None


def test_attested_with_no_citations_is_downgraded():
    assert acceptable_basis_gate(_draft(evidence_refs=[]), []) is not None


def test_attested_with_policy_passes_gate():
    assert acceptable_basis_gate(_draft(), [_cite("a", source_type="policy")]) is None


def test_attested_with_approved_answer_passes_gate():
    # A prior approved answer IS an acceptable basis (reuse rule); the pipeline then
    # resolves it server-side and flags it for human re-confirmation.
    cited = [_cite("a", source_type="approved_answer")]
    assert acceptable_basis_gate(_draft(), cited) is None


def test_qualified_with_control_passes_gate():
    cited = [_cite("a", source_type="control")]
    assert acceptable_basis_gate(_draft(outcome=RespondOutcome.QUALIFIED), cited) is None


def test_negative_outcome_skips_basis_gate():
    assert acceptable_basis_gate(_draft(outcome=RespondOutcome.NEGATIVE), []) is None


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


# --- certification claims (structural, polarity-aware; 07 §3.3) -------------
# These three pin the FedRAMP fix: read the declared claim STATUS, not the prose.

def test_denied_certification_is_never_flagged():
    # The FedRAMP fix: a grounded "No, not FedRAMP authorized" must NOT trip the cert
    # validator — a denial is never an overclaim, regardless of held attestations.
    claims = [_claim("FedRAMP", "denied", basis=["chunk-cmp04"])]
    assert validate_certification_claims(claims, available_certs=set()) == []


def test_affirmed_certification_without_attestation_is_flagged():
    # A genuine overclaim — "We are FedRAMP authorized" with no held attestation — still fires.
    reasons = validate_certification_claims([_claim("FedRAMP", "affirmed")], {"soc 2"})
    assert reasons and "FedRAMP" in reasons[0]


def test_mixed_answer_flags_only_unsupported_affirmation():
    # "SOC 2 certified, not FedRAMP", no held attestations: the SOC 2 affirmation is the only
    # overclaim; the FedRAMP DENIAL is never flagged. Per-claim, polarity-aware.
    claims = [
        _claim("SOC 2", "affirmed"),
        _claim("FedRAMP", "denied", basis=["chunk-cmp04"]),
    ]
    reasons = validate_certification_claims(claims, available_certs=set())
    assert reasons and "SOC 2" in reasons[0]
    assert "FedRAMP" not in reasons[0]


def test_affirmed_certification_with_attestation_passes():
    claims = [_claim("SOC 2", "affirmed", basis=["chunk-soc2"])]
    assert validate_certification_claims(claims, available_certs={"soc 2"}) == []


def test_non_certification_claim_is_ignored_by_cert_validator():
    # Phase 1 scopes the cert validator to certification claims only.
    claims = [_claim("encryption at rest", "affirmed", claim_type=ClaimType.CONTROL)]
    assert validate_certification_claims(claims, available_certs=set()) == []


def test_normalize_cert_maps_subject_variants():
    assert normalize_cert("FedRAMP") == "fedramp"
    assert normalize_cert("SOC2") == "soc 2"
    assert normalize_cert("ISO/IEC 27001") == "iso 27001"
    assert normalize_cert("PCI DSS") == "pci dss"


def test_normalize_cert_covers_iso_family_distinctly():
    # The ISO extensions are separate certifications — recognized, not conflated with 27001.
    assert normalize_cert("ISO 27017") == "iso 27017"
    assert normalize_cert("ISO/IEC 27018") == "iso 27018"
    assert normalize_cert("ISO 27701") == "iso 27701"
    assert normalize_cert("ISO 27001") == "iso 27001"


# --- attested-cert extraction (evidence-derived held set; 07 §3.3/§5) -------

def test_extract_attested_certs_reads_iso_family_from_document_text():
    # The ISO family is extracted from the certificate's OWN text — generically (any 27xxx), so
    # an arbitrary org's certificate grounds whatever extensions it actually lists.
    text = (
        "Standards: ISO/IEC 27001:2022, ISO/IEC 27017:2015, ISO/IEC 27018:2019, "
        "ISO/IEC 27701:2019."
    )
    assert extract_attested_certifications(text, "iso_certificate") == [
        "iso 27001", "iso 27017", "iso 27018", "iso 27701"
    ]


def test_extract_attested_certs_is_anchored_by_document_kind():
    # A SOC 2 report that merely name-drops ISO does NOT attest ISO (kind-anchored).
    assert extract_attested_certifications(
        "SOC 2 Type II report. We may pursue ISO 27001 in future.", "soc2_report"
    ) == ["soc 2"]
    assert extract_attested_certifications(
        "PCI DSS Attestation of Compliance.", "pci_aoc"
    ) == ["pci dss"]


def test_extract_attested_certs_empty_for_non_attestation_documents():
    assert extract_attested_certifications("Mentions ISO 27001.", "policy") == []
    assert extract_attested_certifications("ISO 27001", None) == []


# --- held ISO family vs. genuinely-not-held cert ----------------------------

# Stand-in for the evidence-derived held set: the org's ingested ISO certificate attests the
# whole family (27001/27017/27018/27701); a held cert is one some attestation actually covers.
_HELD = {"soc 2", "iso 27001", "iso 27017", "iso 27018", "iso 27701", "pci dss"}


def test_held_iso_extensions_are_not_flagged():
    claims = [
        _claim("ISO 27001", "affirmed"),
        _claim("ISO 27017", "affirmed"),
        _claim("ISO/IEC 27018", "affirmed"),
        _claim("ISO 27701", "affirmed"),
    ]
    assert validate_certification_claims(claims, available_certs=_HELD) == []


def test_not_held_cert_still_flags_alongside_held_extension():
    # Overclaim guard intact: ISO 9001 (a real cert the org does NOT hold) affirmed without a
    # held attestation still flags, while the held ISO 27017 in the same answer does not.
    claims = [_claim("ISO 27017", "affirmed"), _claim("ISO 9001", "affirmed")]
    reasons = validate_certification_claims(claims, available_certs=_HELD)
    assert reasons and "ISO 9001" in reasons[0]
    assert "27017" not in reasons[0]


def test_held_extension_affirmation_derives_attested():
    # The fix: a held extension affirmed alongside the held primary → attested (NOT collapsed).
    claims = [_claim("ISO 27001", "affirmed", basis=["c1"]), _claim("ISO 27017", "affirmed")]
    assert derive_cert_outcome(claims, available_certs=_HELD) == RespondOutcome.ATTESTED


def test_iso_family_specificity_held_set_of_only_27001_flags_siblings():
    # Regression (07 §3.3/§5): the generic ISO 27xxx recognizer matches FORMAT generically but
    # held-status stays PER STANDARD — the family is never collapsed onto one canonical name.
    # With only ISO 27001 held, the primary affirmation is clean while any sibling is an
    # overclaim. (No DB: runs everywhere, so the guarantee can't silently skip.)
    held = {"iso 27001"}
    assert validate_certification_claims([_claim("ISO 27001", "affirmed")], held) == []
    for sibling in ("ISO 27017", "ISO 27018", "ISO 27701", "ISO/IEC 27701:2019"):
        reasons = validate_certification_claims([_claim(sibling, "affirmed")], held)
        assert reasons and sibling in reasons[0], f"{sibling} must flag as an overclaim"
    # The property that makes the above hold: normalization keeps each 27xxx distinct.
    assert normalize_cert("ISO 27017") == "iso 27017"
    assert normalize_cert("ISO/IEC 27701:2019") == "iso 27701"
    assert len({
        normalize_cert(s) for s in ("ISO 27001", "ISO 27017", "ISO 27018", "ISO 27701")
    }) == 4


def test_unheld_extension_in_narrow_holdings_would_collapse_to_needs_input():
    # The BUG, pinned: if the held set is narrow ({iso 27001} only — e.g. the certificate didn't
    # attest the extensions), an affirmed ISO 27017 reads as an overclaim and sinks the whole
    # answer to needs_input. The evidence-derived held set that includes what the ISO certificate
    # actually attests (test above) is the fix — fail-without / pass-with, at the logic level.
    claims = [_claim("ISO 27001", "affirmed", basis=["c1"]), _claim("ISO 27017", "affirmed")]
    assert derive_cert_outcome(claims, available_certs={"iso 27001"}) == RespondOutcome.NEEDS_INPUT


def test_fedramp_fix_prose_scan_would_flag_but_structure_does_not():
    # Regression pin: the OLD prose scan saw the cert keyword in a correct negative and flagged
    # it; the structural per-claim check does not. This is the bug, fixed structurally.
    assert asserted_certifications("No. Northwind is not FedRAMP authorized.") == {"fedramp"}
    claims = [_claim("FedRAMP", "denied", basis=["chunk-cmp04"])]
    assert validate_certification_claims(claims, available_certs=set()) == []


# --- certification outcome derived from claim status (07 §3.2) --------------

def test_derive_cert_outcome_none_when_no_cert_claims():
    assert derive_cert_outcome([], available_certs=set()) is None


def test_derive_cert_outcome_grounded_denial_is_negative():
    claims = [_claim("FedRAMP", "denied", basis=["chunk-cmp04"])]
    assert derive_cert_outcome(claims, available_certs=set()) == RespondOutcome.NEGATIVE


def test_derive_cert_outcome_ungrounded_denial_is_needs_input():
    assert derive_cert_outcome([_claim("FedRAMP", "denied")], set()) == RespondOutcome.NEEDS_INPUT


def test_derive_cert_outcome_affirmed_with_attestation_is_attested():
    claims = [_claim("SOC 2", "affirmed", basis=["chunk-soc2"])]
    assert derive_cert_outcome(claims, available_certs={"soc 2"}) == RespondOutcome.ATTESTED


def test_derive_cert_outcome_overclaim_is_needs_input():
    assert derive_cert_outcome([_claim("FedRAMP", "affirmed")], {"soc 2"}) == (
        RespondOutcome.NEEDS_INPUT
    )


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
    draft = _draft(evidence_refs=["ghost"])
    reasons = run_review_checks(
        draft,
        [_cite("a", shareable=False)],
        grounding_refs=["a"],
        claims=[_claim("SOC 1", "affirmed")],
        available_certs={"soc 2"},
        customer_facing=True,
    )
    # citation + cert (structural) + shareability all fire.
    assert len(reasons) >= 3
