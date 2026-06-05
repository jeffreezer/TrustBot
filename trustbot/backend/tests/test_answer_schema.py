"""Schema enforcement at the generator trust boundary."""
import pytest
from pydantic import ValidationError

from app.answers.schema import (
    AnswerDraft,
    ConfidenceBand,
    GeneratedAnswer,
    Outcome,
)


def test_valid_draft_parses():
    draft = AnswerDraft.model_validate_json(
        '{"outcome": "supported_yes", "short_answer": "Yes.", "claim": "c", '
        '"evidence_refs": ["a", "b"]}'
    )
    assert draft.outcome == Outcome.SUPPORTED_YES
    assert draft.evidence_refs == ["a", "b"]


def test_invalid_outcome_rejected():
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate_json('{"outcome": "definitely_yes"}')


def test_missing_outcome_rejected():
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate_json('{"short_answer": "Yes."}')


def test_extra_keys_ignored():
    draft = AnswerDraft.model_validate_json(
        '{"outcome": "unknown", "model_note": "no evidence", "hallucinated": 1}'
    )
    assert draft.outcome == Outcome.UNKNOWN


def test_generated_answer_confidence_range_enforced():
    base = dict(
        question="q",
        outcome=Outcome.SUPPORTED_YES,
        confidence_band=ConfidenceBand.HIGH,
    )
    GeneratedAnswer(confidence=0.5, **base)  # ok
    with pytest.raises(ValidationError):
        GeneratedAnswer(confidence=1.5, **base)
    with pytest.raises(ValidationError):
        GeneratedAnswer(confidence=-0.1, **base)
