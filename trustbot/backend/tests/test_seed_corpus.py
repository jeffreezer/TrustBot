"""Tests for the structured-source ingestion added in the Phase 2 corpus expansion.

Covers the text-composition helpers that turn control and approved-answer rows into
retrieval text, and the ``ingest_text`` tenant-scoping guard. All offline / DB-free:
SQLAlchemy models can be instantiated in memory without a session.
"""
import uuid

import pytest

from app.db.models import ApprovedAnswer, Control
from app.ingestion import IngestionError, ingest_text
from app.providers.hash_embedder import HashEmbeddingProvider
from app.seed import _approved_answer_text, _control_text


def test_control_text_includes_code_title_and_statement():
    control = Control(
        control_code="CC6.1",
        title="Logical access controls",
        implementation_statement="Access is provisioned via Okta SSO with mandatory MFA.",
    )
    text = _control_text(control)
    assert "CC6.1" in text
    assert "Logical access controls" in text
    assert "Okta SSO" in text


def test_control_text_without_statement_is_just_code_and_title():
    control = Control(control_code="CC1.1", title="Governance", implementation_statement=None)
    assert _control_text(control) == "CC1.1 Governance"


def test_approved_answer_text_composes_qa_pair():
    answer = ApprovedAnswer(
        source="CAIQ v4.0.3",
        question_external_id="AIS-01",
        question_text="Do you encrypt data at rest?",
        answer_text="Yes",
        answer_detail="AES-256 across all stores.",
    )
    text = _approved_answer_text(answer)
    assert "Q: Do you encrypt data at rest?" in text
    assert "A: Yes" in text
    assert "AES-256" in text


def test_approved_answer_text_blank_when_all_fields_empty():
    answer = ApprovedAnswer(
        source="CAIQ", question_external_id="X", question_text="", answer_text=None
    )
    assert _approved_answer_text(answer) == ""


def test_ingest_text_requires_org_id():
    with pytest.raises(IngestionError):
        ingest_text(
            None,  # never reached: org_id check fires first
            org_id=None,
            source_type="control",
            source_id=uuid.uuid4(),
            text="some control text",
            provider=HashEmbeddingProvider(),
        )
