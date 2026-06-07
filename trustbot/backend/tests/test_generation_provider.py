"""The deterministic fake generator — respond posture: grounding-only, composes (never
echoes), suppresses SOC 2 exception commentary, and classifies document-requests."""
from app.answers.schema import AnswerDraft, RespondOutcome
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


def test_no_grounding_returns_needs_input():
    assert _draft("Are you FedRAMP authorized?", ()).outcome == RespondOutcome.NEEDS_INPUT


def test_grounded_answer_cites_and_composes():
    draft = _draft("What are your data classification levels?", (POLICY,))
    assert draft.outcome == RespondOutcome.ATTESTED
    assert draft.evidence_refs == ["policy-1"]
    # Composes with a fresh prefix rather than echoing the chunk verbatim.
    assert draft.short_answer.startswith("Yes.")
    # The four tiers survive into the answer body.
    for tier in ("Public", "Internal", "Confidential", "Restricted"):
        assert tier in draft.answer


def test_negative_cue_yields_negative():
    cmek = GroundingDoc(
        ref="wp-1",
        source_type="evidence",
        title="Whitepaper",
        text="Customer-managed encryption keys (CMEK/BYOK) are on the roadmap for H2 2026; "
        "today encryption uses Northwind-managed keys.",
        customer_shareable=True,
    )
    assert _draft("Do you support CMEK/BYOK?", (cmek,)).outcome == RespondOutcome.NEGATIVE


def test_soc2_exception_is_suppressed_and_stays_attested():
    soc2 = GroundingDoc(
        ref="soc2-1",
        source_type="evidence",
        title="SOC 2",
        text="Access reviews are performed quarterly. The auditor noted an exception: 2 of 25 "
        "terminated users were revoked late; management has since automated deprovisioning.",
        customer_shareable=True,
    )
    draft = _draft("Do you perform access reviews?", (soc2,))
    # Respond posture: the exception does NOT downgrade the answer or surface as commentary.
    assert draft.outcome == RespondOutcome.ATTESTED
    assert not hasattr(draft, "exceptions")
    assert "exception" not in draft.short_answer.lower()


def test_qualified_cue_yields_qualified_with_scope():
    tiered = GroundingDoc(
        ref="ev-1",
        source_type="evidence",
        title="SSO",
        text="SAML single sign-on is available on the Enterprise tier for all customers.",
        customer_shareable=True,
    )
    draft = _draft("Do you support SAML SSO?", (tiered,))
    assert draft.outcome == RespondOutcome.QUALIFIED
    assert draft.scope


def test_document_request_sets_requires_document():
    soc2 = GroundingDoc(
        ref="ev-1",
        source_type="evidence",
        title="SOC 2 Type II report",
        text="Northwind maintains a current SOC 2 Type II report covering security and "
        "availability.",
        customer_shareable=True,
    )
    draft = _draft("Please provide a copy of your SOC 2 report.", (soc2,))
    assert draft.requires_document is True
    assert draft.outcome in {RespondOutcome.ATTESTED, RespondOutcome.QUALIFIED}


def test_attestation_question_does_not_require_document():
    draft = _draft("What are your data classification levels?", (POLICY,))
    assert draft.requires_document is False


def test_synthesis_prefers_authoritative_second_chunk_over_weak_first():
    # #1 is a vague approved answer; #2 is the authoritative policy that lists the tiers.
    draft = _draft(
        "What are your data classification levels?", (VAGUE_APPROVED, POLICY)
    )
    # The fake answers from the policy (lists tiers) and cites it — not the #1 chunk only.
    assert "policy-1" in draft.evidence_refs
    assert "Confidential" in draft.answer and "Restricted" in draft.answer


def test_irrelevant_grounding_returns_needs_input():
    off_topic = GroundingDoc(
        ref="x",
        source_type="policy",
        title="Vacation Policy",
        text="Employees accrue paid time off each month.",
        customer_shareable=True,
    )
    out = _draft("Do you encrypt data at rest?", (off_topic,)).outcome
    assert out == RespondOutcome.NEEDS_INPUT
