"""Policy header parsing — DB-free tests for the classification + control-link logic.

These pin the rules that govern shareability of policy documents (a security-relevant
mapping) and how Related-controls headers become control links.
"""
from app.seed import (
    _classify_policy,
    _extract_policy_header,
    _extract_title,
    _parse_related_controls,
)

INFOSEC_HEADER = """# Northwind AI — Information Security Policy

> **Owner:** CISO · **Version:** 2.0
> **Classification:** Public (umbrella overview; suitable for external sharing)
> **Related controls:** CC1.1, CC1.4, CC2.1

## 1. Purpose
Body text here.
"""

ACCESS_HEADER = """# Northwind AI — Access Control Policy

> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** CC6.1, CC6.2, CC6.3, IAM (catalog)
"""

ACCEPTABLE_USE_HEADER = """# Acceptable Use Policy

> **Classification:** Internal
> **Related controls:** CC1.1, HR1.2
"""


def test_public_classification_is_public_and_shareable():
    assert _classify_policy("Public (umbrella overview)") == ("public", True)


def test_customer_shareable_internal_is_confidential_and_shareable():
    assert _classify_policy("Internal — customer-shareable on request (NDA)") == (
        "confidential",
        True,
    )


def test_plain_internal_is_internal_and_not_shareable():
    assert _classify_policy("Internal") == ("internal", False)


def test_parse_related_controls_strips_catalog_family_refs():
    codes = _parse_related_controls("CC6.1, CC6.2, CC6.3, IAM (catalog)")
    # "(catalog)" suffix dropped; the bare family name stays (linker skips non-matches).
    assert codes == ["CC6.1", "CC6.2", "CC6.3", "IAM"]


def test_parse_related_controls_dedupes_preserving_order():
    assert _parse_related_controls("P6.1, C1.2, P6.1") == ["P6.1", "C1.2"]


def test_extract_header_pulls_classification_and_controls():
    classification, related = _extract_policy_header(ACCESS_HEADER)
    assert classification.startswith("Internal — customer-shareable")
    assert related == ["CC6.1", "CC6.2", "CC6.3", "IAM"]


def test_extract_header_handles_public_umbrella():
    classification, related = _extract_policy_header(INFOSEC_HEADER)
    assert _classify_policy(classification) == ("public", True)
    assert related == ["CC1.1", "CC1.4", "CC2.1"]


def test_extract_header_plain_internal():
    classification, related = _extract_policy_header(ACCEPTABLE_USE_HEADER)
    assert _classify_policy(classification) == ("internal", False)
    assert related == ["CC1.1", "HR1.2"]


def test_extract_title_uses_h1_then_fallback():
    assert _extract_title(INFOSEC_HEADER, "fallback") == (
        "Northwind AI — Information Security Policy"
    )
    assert _extract_title("no heading here\njust text", "the-fallback") == "the-fallback"
