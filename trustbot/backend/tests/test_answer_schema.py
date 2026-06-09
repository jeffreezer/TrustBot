"""Schema enforcement at the generator trust boundary (respond mode)."""
import pytest
from pydantic import ValidationError

from app.answers.schema import (
    AnswerDraft,
    Claim,
    ClaimStatus,
    ClaimType,
    ConfidenceBand,
    GeneratedAnswer,
    RespondOutcome,
)


def test_valid_draft_parses():
    draft = AnswerDraft.model_validate_json(
        '{"outcome": "attested", "short_answer": "Yes.", "claim": "c", '
        '"evidence_refs": ["a", "b"], "requires_document": true}'
    )
    assert draft.outcome == RespondOutcome.ATTESTED
    assert draft.evidence_refs == ["a", "b"]
    assert draft.requires_document is True


def test_invalid_outcome_rejected():
    # Review-mode outcomes are not valid in respond mode.
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate_json('{"outcome": "supported_yes"}')
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate_json('{"outcome": "definitely_yes"}')


def test_missing_outcome_rejected():
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate_json('{"short_answer": "Yes."}')


def test_extra_keys_ignored():
    draft = AnswerDraft.model_validate_json(
        '{"outcome": "needs_input", "model_note": "no evidence", "hallucinated": 1}'
    )
    assert draft.outcome == RespondOutcome.NEEDS_INPUT
    assert draft.model_note == "no evidence"


def test_generated_answer_confidence_range_enforced():
    base = dict(
        question="q",
        outcome=RespondOutcome.ATTESTED,
        confidence_band=ConfidenceBand.HIGH,
    )
    GeneratedAnswer(confidence=0.5, **base)  # ok
    with pytest.raises(ValidationError):
        GeneratedAnswer(confidence=1.5, **base)
    with pytest.raises(ValidationError):
        GeneratedAnswer(confidence=-0.1, **base)


def test_generated_answer_respond_attributes_default_empty():
    ga = GeneratedAnswer(
        question="q",
        outcome=RespondOutcome.NEEDS_INPUT,
        confidence=0.0,
        confidence_band=ConfidenceBand.NONE,
    )
    assert ga.requires_document is False
    assert ga.provided_documents == []
    assert ga.remediation_required is False
    assert ga.finding_refs == []
    assert ga.claims == []  # claim/attestation model (07): default empty, never a ceremony


# --- structured claims (07 §3.1) -------------------------------------------

def test_answer_draft_claims_default_empty_and_parse():
    plain = AnswerDraft.model_validate_json('{"outcome": "negative", "short_answer": "No."}')
    assert plain.claims == []  # a plain answer carries no claims
    drafted = AnswerDraft.model_validate_json(
        '{"outcome": "negative", "claims": [{"subject": "FedRAMP", '
        '"claim_type": "certification", "status": "denied", "basis": ["c1"]}]}'
    )
    assert drafted.claims[0].subject == "FedRAMP"
    assert drafted.claims[0].claim_type is ClaimType.CERTIFICATION
    assert drafted.claims[0].status is ClaimStatus.DENIED
    assert drafted.claims[0].basis == ["c1"]


def test_claim_rejects_invalid_status():
    with pytest.raises(ValidationError):
        Claim(subject="FedRAMP", status="maybe")


def test_claim_defaults_are_lightweight():
    c = Claim(subject="SOC 2", status=ClaimStatus.AFFIRMED)
    assert c.claim_type is ClaimType.CERTIFICATION  # Phase 1 default
    assert c.basis == [] and c.confidence is None and c.customer_shareable is True
