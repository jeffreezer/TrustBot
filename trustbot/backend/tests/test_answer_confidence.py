"""Composite confidence — relevance + authority + agreement + coverage, NOT rerank.

The load-bearing case: an answer stated verbatim in an authoritative policy must be
HIGH confidence even when the rerank logit is modest (or negative).
"""
from app.answers.confidence import SOURCE_AUTHORITY, band_for, compute_confidence
from app.answers.schema import CitedEvidence, ConfidenceBand


def _cite(source_type, text, *, source_id="s", rerank=0.0, shareable=True):
    return CitedEvidence(
        chunk_id=f"c-{source_id}",
        source_type=source_type,
        source_id=source_id,
        title=source_type,
        text=text,
        customer_shareable=shareable,
        confidentiality="confidential",
        rerank_score=rerank,
        fusion_score=0.03,
    )


TIERS_TEXT = "data classification tiers public internal confidential restricted levels"


def test_authoritative_policy_with_modest_rerank_is_high():
    cited = [_cite("policy", TIERS_TEXT, rerank=0.04)]
    score, factors, band = compute_confidence("data classification levels tiers", cited)
    assert band == ConfidenceBand.HIGH
    assert factors["authority"] == 1.0


def test_authoritative_policy_even_with_negative_rerank_is_high():
    # Rerank is relevance-only and uncalibrated; a negative logit must not sink an
    # answer quoted verbatim from an authoritative source.
    cited = [_cite("policy", TIERS_TEXT, rerank=-3.0)]
    _, factors, band = compute_confidence("data classification levels tiers", cited)
    assert factors["relevance"] < 0.5  # squashed below midpoint
    assert band == ConfidenceBand.HIGH


def test_no_evidence_is_zero_confidence_none_band():
    score, factors, band = compute_confidence("anything", [])
    assert score == 0.0
    assert band == ConfidenceBand.NONE
    assert all(v == 0.0 for v in factors.values())


def test_cross_source_agreement_raises_confidence():
    one = compute_confidence("encryption at rest aes", [_cite("control", "encryption at rest aes 256", source_id="a")])[0]
    two = compute_confidence(
        "encryption at rest aes",
        [
            _cite("control", "encryption at rest aes 256", source_id="a"),
            _cite("evidence", "encryption at rest aes 256 whitepaper", source_id="b"),
        ],
    )[0]
    assert two > one


def test_approved_answer_authority_below_primary_sources():
    assert SOURCE_AUTHORITY["approved_answer"] < SOURCE_AUTHORITY["policy"]
    assert SOURCE_AUTHORITY["approved_answer"] < SOURCE_AUTHORITY["evidence"]


def test_band_thresholds():
    assert band_for(0.9) == ConfidenceBand.HIGH
    assert band_for(0.5) == ConfidenceBand.MEDIUM
    assert band_for(0.25) == ConfidenceBand.LOW
    assert band_for(0.1) == ConfidenceBand.NONE
