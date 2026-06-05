# Northwind AI — PCI DSS Attestation of Compliance (Service Provider)

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Structure modeled on the PCI SSC AOC for Report on Compliance — Service Providers, PCI DSS v4.0.1.

**PCI DSS Version:** 4.0.1
**Document type:** Attestation of Compliance (AOC) for Report on Compliance — Service Providers

## Section 1: Assessment Information

| Field | Value |
|---|---|
| Entity name | Northwind AI, Inc. |
| Doing business as | Northwind AI |
| Entity contact | compliance@northwind.ai |
| Assessor company | Coastline QSA Services (fictional QSA) |
| Date assessment ended | February 6, 2026 |
| Date of report (RoC) | February 18, 2026 |
| AOC valid through | February 18, 2027 |

### Scope of Assessment

The assessment covered the systems and processes supporting **billing and payment for Northwind subscription services**. Cardholder data is processed by a PCI DSS validated third-party payment processor (Stripe). Northwind does not store cardholder data. The assessed scope covers Northwind's billing integration, tokenization handling, and the supporting network segment.

### Services Assessed

- Subscription billing and payment processing integration (tokenized).
- Supporting cardholder data environment (CDE) segment and connected systems.

### Services NOT Assessed

- The core Northwind Assistant and Northwind API model-serving services (out of CDE scope; cardholder data is not submitted to or processed by these services).

## Section 2: Assessment Findings

| Item | Result |
|---|---|
| Overall compliance status | **Compliant** |
| Assessment approach | Full assessment against applicable PCI DSS v4.0.1 requirements for service providers |
| Requirements applicable | All applicable requirements were assessed and found In Place, with non-applicable requirements documented and justified (e.g., requirements specific to storage of cardholder data, which Northwind does not perform). |

## Section 3: Validation and Attestation

Northwind AI, Inc. attests that, based on the results documented in the Report on Compliance dated February 18, 2026, it has met the applicable PCI DSS v4.0.1 requirements for service providers for the billing scope described above. Cardholder data storage is avoided through use of a validated third-party processor and tokenization.

**Signed (synthetic):** VP, Engineering & Head of GRC, Northwind AI, Inc.
