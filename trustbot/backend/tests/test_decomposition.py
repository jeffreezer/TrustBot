"""Explicit decomposition of compound questions (Phase 6, 06 §5) — offline + deterministic.

The FakeGenerationProvider splits on sentence/`;` boundaries and answers each part from the
(monkeypatched) loop retrieval, so the per-part path is exercised without a network. Pins:
four-part fan-out with per-part citations, an unsupported part flagged (not collapsed), the
combined-outcome rule, the sub-question cap, and that a simple question is NOT decomposed.
"""
import uuid
from types import SimpleNamespace

import app.answers.agent_tools as tools
import app.answers.generate as gen
from app.answers import RespondOutcome, generate_answer
from app.answers.generate import _decompose, _recompose
from app.answers.schema import ConfidenceBand, EvidenceRef, GeneratedAnswer
from app.providers.fake_generator import FakeGenerationProvider
from app.retrieval import RetrievedChunk

ORG = SimpleNamespace(id=uuid.uuid4(), name="Northwind AI")


def _chunk(text, *, source_type="policy"):
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_type=source_type,
        source_id=uuid.uuid4(),
        chunk_text=text,
        meta={"title": "Policy", "customer_shareable": True, "confidentiality": "confidential"},
        fusion_score=0.03,
        rerank_score=2.0,
    )


def _patch(monkeypatch, *, no_evidence=()):
    """Loop retrieval returns a relevant policy chunk for each sub-question — except queries
    matching ``no_evidence`` (those return nothing → that part is unsupported)."""

    def _retrieve(session=None, *, query, filters=None, top_k=5):
        if any(k in query.lower() for k in no_evidence):
            return []
        return [_chunk(f"{query} This is addressed by our security policy and controls.")]

    monkeypatch.setattr(tools, "retrieve", _retrieve)
    monkeypatch.setattr(gen, "_resolve_documents_and_findings", lambda *a, **k: gen._DocResolution())
    monkeypatch.setattr(gen, "_resolve_reused_approvals", lambda *a, **k: [])
    monkeypatch.setattr(gen, "_available_certs", lambda *a, **k: set())
    monkeypatch.setattr(gen, "_freshness", lambda *a, **k: "current")


FOUR_PART = (
    "Do you encrypt data at rest? "
    "Do you manage encryption keys? "
    "Do you rotate encryption keys? "
    "Do you support regional data residency?"
)


def test_four_part_question_returns_four_per_part_answers(monkeypatch):
    _patch(monkeypatch)
    ga = generate_answer(None, org=ORG, question=FOUR_PART, generator=FakeGenerationProvider())
    assert ga.retrieval_path == "decomposed"
    assert len(ga.sub_answers) == 4
    # Each part has its own outcome + its own citations.
    assert all(s.outcome == RespondOutcome.ATTESTED for s in ga.sub_answers)
    assert all(s.evidence_refs for s in ga.sub_answers)
    # Distinct evidence per part (focused grounding, not one shared pull).
    per_part_refs = [{r.chunk_id for r in s.evidence_refs} for s in ga.sub_answers]
    assert per_part_refs[0] != per_part_refs[1]
    assert ga.outcome == RespondOutcome.ATTESTED


def test_unsupported_part_is_flagged_while_others_answered(monkeypatch):
    # The FedRAMP part has no evidence; the encryption part does.
    _patch(monkeypatch, no_evidence=("fedramp",))
    ga = generate_answer(
        None,
        org=ORG,
        question="Do you encrypt data at rest? Are you FedRAMP authorized?",
        generator=FakeGenerationProvider(),
    )
    assert len(ga.sub_answers) == 2
    by_outcome = {s.outcome for s in ga.sub_answers}
    assert RespondOutcome.ATTESTED in by_outcome
    assert RespondOutcome.NEEDS_INPUT in by_outcome  # unsupported part kept, not dropped
    # The whole question does NOT collapse to needs_input; supported part is answered.
    assert ga.outcome == RespondOutcome.QUALIFIED
    assert ga.needs_human_review is True
    assert "human review" in (ga.review_reason or "").lower()


# --- combined-outcome rule (unit test of _recompose) ------------------------

def _part(outcome, *, review=False, conf=0.8):
    return GeneratedAnswer(
        question="part",
        outcome=outcome,
        short_answer="s",
        answer="a",
        evidence_refs=[EvidenceRef(chunk_id=str(uuid.uuid4()), source_type="policy")],
        confidence=conf,
        confidence_band=ConfidenceBand.HIGH,
        needs_human_review=review,
    )


def _combine(outcomes):
    parts = [_part(o) for o in outcomes]
    subqs = [f"part {i}" for i in range(len(parts))]
    return _recompose("compound q", subqs, parts, "respond:test")


def test_combined_outcome_all_attested():
    ga = _combine([RespondOutcome.ATTESTED, RespondOutcome.ATTESTED])
    assert ga.outcome == RespondOutcome.ATTESTED
    assert ga.needs_human_review is False


def test_combined_outcome_mixed_support_is_qualified():
    ga = _combine([RespondOutcome.ATTESTED, RespondOutcome.QUALIFIED])
    assert ga.outcome == RespondOutcome.QUALIFIED
    ga2 = _combine([RespondOutcome.ATTESTED, RespondOutcome.NEGATIVE])
    assert ga2.outcome == RespondOutcome.QUALIFIED


def test_combined_outcome_one_unsupported_stays_qualified_with_review():
    ga = _combine([RespondOutcome.ATTESTED, RespondOutcome.NEEDS_INPUT])
    assert ga.outcome == RespondOutcome.QUALIFIED  # not a whole-question collapse
    assert ga.needs_human_review is True
    assert len(ga.sub_answers) == 2  # the unsupported part is still present


def test_combined_outcome_none_supported_is_needs_input():
    ga = _combine([RespondOutcome.NEEDS_INPUT, RespondOutcome.NEEDS_INPUT])
    assert ga.outcome == RespondOutcome.NEEDS_INPUT
    assert ga.needs_human_review is True


# --- bounds + no-regression -------------------------------------------------

def test_subquestion_count_is_bounded(monkeypatch):
    monkeypatch.setattr(gen.settings, "agent_max_subquestions", 3, raising=False)
    five = "a? b? c? d? e?"
    parts = _decompose(None, ORG, five, FakeGenerationProvider())
    assert len(parts) == 3  # capped


def test_simple_question_is_not_decomposed(monkeypatch):
    _patch(monkeypatch)
    # If decomposition ran, sub_answers would be populated and path would be "decomposed".
    monkeypatch.setattr(gen, "retrieve", lambda *a, **k: [_chunk("AES-256 at rest")])
    ga = generate_answer(
        None, org=ORG, question="Do you encrypt data at rest?", generator=FakeGenerationProvider()
    )
    assert ga.sub_answers == []
    assert ga.retrieval_path == "fixed"
