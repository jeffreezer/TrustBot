"""Boundary validation for the review-workspace request bodies."""
import pytest
from pydantic import ValidationError

from app.review_routes import GenerateRequest, ReviewRequest


def test_generate_request_defaults_to_no_regenerate():
    assert GenerateRequest().regenerate is False


@pytest.mark.parametrize(
    "action",
    ["approve", "edit", "reject", "request_evidence", "save_to_library"],
)
def test_review_request_accepts_known_actions(action):
    assert ReviewRequest(action=action).action == action


def test_review_request_rejects_unknown_action():
    with pytest.raises(ValidationError):
        ReviewRequest(action="nuke")


def test_review_request_bounds_edited_text():
    with pytest.raises(ValidationError):
        ReviewRequest(action="edit", edited_text="x" * 20001)


def test_review_request_bounds_reviewer():
    with pytest.raises(ValidationError):
        ReviewRequest(action="approve", reviewer="r" * 256)
