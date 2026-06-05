"""The deterministic fake generator — grounding-only, composes (never echoes), and
synthesizes over the full top-k rather than the #1 chunk alone."""
from app.answers.schema import AnswerDraft, Outcome
from app.providers import DraftRequest, GroundingDoc
from app.providers.fake_generator import FakeGenerationProvider

GEN = FakeGenerationProvider()


def _draft(question: str, grounding: tuple[GroundingDoc, ...]) -> AnswerDraft:
    raw = GEN.draft(DraftRequest(question=question, instructions="sys", grounding=grounding))
    return AnswerDraft.model_validate_json(raw)


POLICY = GroundingDoc(
    ref="policy-1",
    source_type="policy",
    title="Data Classification & Handling Policy",
    text="# Data Classification & Handling Policy\n## Classification Tiers\n"
    "- Public\n- Internal\n- Confidential\n- Restricted",
    customer_shareable=True,
)
VAGUE_APPROVED = GroundingDoc(
    ref="aa-1",
    source_type="approved_answer",
    title="CAIQ DSP-04",
    text="Q: Is data classified? A: Yes. Data is classified per a documented policy.",
    customer_shareable=True,
)


def test_no_grounding_returns_unknown():
    assert _draft("Are you FedRAMP authorized?", ()).outcome == Outcome.UNKNOWN


def test_grounded_answer_cites_and_composes():
    draft = _draft("What are your data classification levels?", (POLICY,))
    assert draft.outcome == Outcome.SUPPORTED_YES
    assert draft.evidence_refs == ["policy-1"]
    # Composes with a fresh prefix rather than echoing the chunk verbatim.
    assert draft.short_answer.startswith("Yes.")
    # The four tiers survive into the answer body.
    for tier in ("Public", "Internal", "Confidential", "Restricted"):
        assert tier in draft.answer


def test_negative_cue_yields_supported_no():
    cmek = GroundingDoc(
        ref="wp-1",
        source_type="evidence",
        title="Whitepaper",
        text="Customer-managed encryption keys (CMEK/BYOK) are on the roadmap for H2 2026; "
        "today encryption uses Northwind-managed keys.",
        customer_shareable=True,
    )
    assert _draft("Do you support CMEK/BYOK?", (cmek,)).outcome == Outcome.SUPPORTED_NO


def test_exception_cue_yields_has_exception():
    soc2 = GroundingDoc(
        ref="soc2-1",
        source_type="evidence",
        title="SOC 2",
        text="The auditor noted an exception: 2 of 25 terminated users were revoked late.",
        customer_shareable=True,
    )
    draft = _draft("Were any exceptions noted in your SOC 2 report?", (soc2,))
    assert draft.outcome == Outcome.HAS_EXCEPTION
    assert "exception" in draft.exceptions.lower()


def test_synthesis_prefers_authoritative_second_chunk_over_weak_first():
    # #1 is a vague approved answer; #2 is the authoritative policy that lists the tiers.
    draft = _draft(
        "What are your data classification levels?", (VAGUE_APPROVED, POLICY)
    )
    # The fake answers from the policy (lists tiers) and cites it — not the #1 chunk only.
    assert "policy-1" in draft.evidence_refs
    assert "Confidential" in draft.answer and "Restricted" in draft.answer


def test_irrelevant_grounding_returns_unknown():
    off_topic = GroundingDoc(
        ref="x",
        source_type="policy",
        title="Vacation Policy",
        text="Employees accrue paid time off each month.",
        customer_shareable=True,
    )
    assert _draft("Do you encrypt data at rest?", (off_topic,)).outcome == Outcome.UNKNOWN
