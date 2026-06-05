"""Boundary validation for the /retrieve request body (untrusted input)."""
import pytest
from pydantic import ValidationError

from app.main import RetrieveRequest


def test_defaults_are_sane():
    req = RetrieveRequest(question="Do you encrypt data at rest?")
    assert req.top_k == 5
    assert req.source_types is None
    assert req.customer_shareable is None


def test_empty_question_rejected():
    with pytest.raises(ValidationError):
        RetrieveRequest(question="")


def test_overlong_question_rejected():
    with pytest.raises(ValidationError):
        RetrieveRequest(question="x" * 2001)


@pytest.mark.parametrize("bad_top_k", [0, -1, 21])
def test_top_k_bounds_enforced(bad_top_k):
    with pytest.raises(ValidationError):
        RetrieveRequest(question="q", top_k=bad_top_k)


def test_filters_accepted():
    req = RetrieveRequest(
        question="encryption",
        top_k=3,
        source_types=["evidence", "control"],
        confidentiality=["confidential"],
        customer_shareable=True,
    )
    assert req.source_types == ["evidence", "control"]
    assert req.customer_shareable is True
