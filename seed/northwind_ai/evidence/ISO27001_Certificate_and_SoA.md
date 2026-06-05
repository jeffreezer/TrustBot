# Northwind AI — ISO/IEC Certificate and Statement of Applicability

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** "Meridian Certification Ltd." is a fictional certification body.

## Certificate of Registration

| Field | Value |
|---|---|
| Certified organization | Northwind AI, Inc. |
| Standards | ISO/IEC 27001:2022, ISO/IEC 27017:2015, ISO/IEC 27018:2019, ISO/IEC 27701:2019 |
| Scope | The information security and privacy management system supporting the Northwind Assistant and Northwind API services, including development, operation, and support. |
| Certificate number | NW-ISMS-2024-0417 (fictional) |
| Certification body | Meridian Certification Ltd. (fictional) |
| Original certification | June 2024 |
| Current certificate issued | June 2025 |
| Certificate expiry | June 2027 |
| Surveillance | Annual surveillance audits; next surveillance due June 2026. |

## Statement of Applicability (SoA) — Summary

**Purpose.** This SoA provides an overview of the Annex A controls selected and implemented within Northwind's Information Security and Privacy Management System to address the requirements of ISO/IEC 27001 (with extensions 27017, 27018, 27701). It records applicability, implementation status, and justification.

**Document owner:** Head of GRC
**Version/Status:** 2 / Published
**Approved:** 2025-05-29

### Control Themes (ISO/IEC 27001:2022 Annex A)

| Theme | Applicable | Implementation status | Notes |
|---|---|---|---|
| A.5 Organizational controls | Yes | Implemented | Policies, roles, supplier and incident management, threat intelligence. |
| A.6 People controls | Yes | Implemented | Screening, awareness training, terms of employment, disciplinary process. |
| A.7 Physical controls | Yes | Implemented (mostly inherited) | Datacenter physical security inherited from GCP/AWS; office controls direct. |
| A.8 Technological controls | Yes | Implemented | Access control, cryptography, secure development, logging, vulnerability management, network security. |

### Cloud and Privacy Extensions

| Standard | Applicable | Notes |
|---|---|---|
| ISO/IEC 27017 (cloud security) | Yes | Cloud-specific controls for shared responsibility, virtualization, and admin operations. |
| ISO/IEC 27018 (PII in public cloud) | Yes | Protection of customer PII processed in the cloud; encryption and access restrictions. |
| ISO/IEC 27701 (privacy/PIMS) | Yes | Privacy program; roles of controller/processor; data subject rights support. |

### Notable Exclusions / Justifications

- Controls specific to in-house datacenter physical operations are addressed via the carve-out to GCP/AWS subservice providers.
- Customer-managed encryption keys are not yet a control objective; provider-managed encryption is implemented (roadmap item for H2 2026).
