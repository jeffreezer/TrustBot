# Northwind AI, Inc. — SOC 2 Type 2 Report

> **SYNTHETIC / FICTIONAL DEMO DOCUMENT.** Created for TrustBot test data. "Harbor Assurance LLP" is a fictional auditor. Not a real attestation. Structure modeled on standard SSAE No. 21 SOC 2 Type 2 reports.

**SOC 2 Report for Northwind Assistant and Northwind API Services**
**A Type 2 Independent Service Auditor's Report on Controls Relevant to Security, Availability, Confidentiality, and Privacy**
**Period: January 1, 2025 to December 31, 2025**

Proprietary & Confidential.

---

## Table of Contents

- Section 1 — Independent Service Auditor's Report
- Section 2 — Management's Assertion
- Section 3 — Description of the System
- Section 4 — Testing Matrices (Trust Services Criteria, Controls, Tests, and Results)
- Section 5 — Other Information Provided by Management

---

## Section 1 — Independent Service Auditor's Report

To the Management of Northwind AI, Inc.:

**Scope.** We have examined Northwind AI, Inc.'s ("Northwind") accompanying description of its Northwind Assistant and Northwind API services (the "System") throughout the period January 1, 2025 to December 31, 2025 (the "Description"), based on the criteria for a description of a service organization's system in DC section 200, and the suitability of the design and operating effectiveness of controls stated in the Description to provide reasonable assurance that Northwind's service commitments and system requirements were achieved based on the trust services criteria relevant to Security, Availability, Confidentiality, and Privacy (the "applicable trust services criteria").

**Service organization's responsibilities.** Northwind is responsible for its service commitments and system requirements and for designing, implementing, and operating effective controls within the System to provide reasonable assurance that Northwind's service commitments and system requirements were achieved. Northwind has provided the accompanying assertion (Section 2) about the Description and the suitability of the design and operating effectiveness of controls stated therein.

**Service auditor's responsibilities.** Our responsibility is to express an opinion on the Description and on the suitability of the design and operating effectiveness of controls stated in the Description based on our examination. Our examination was conducted in accordance with attestation standards established by the AICPA.

**Opinion.** In our opinion, in all material respects, the Description presents the System that was designed and implemented throughout the period; the controls stated in the Description were suitably designed and operated effectively throughout the period to provide reasonable assurance that Northwind's service commitments and system requirements were achieved based on the applicable trust services criteria — **except for the matters described in Section 4**, where exceptions in the operating effectiveness of certain controls were noted.

Harbor Assurance LLP (fictional)
Seattle, Washington
February 20, 2026

---

## Section 2 — Management's Assertion

We have prepared the accompanying Description of the Northwind Assistant and Northwind API services throughout the period January 1, 2025 to December 31, 2025, based on the description criteria. We confirm, to the best of our knowledge and belief, that:

a. The Description presents the System that was designed and implemented throughout the period.
b. The controls stated in the Description were suitably designed throughout the period to provide reasonable assurance that Northwind's service commitments and system requirements would be achieved based on the applicable trust services criteria.
c. The controls stated in the Description operated effectively throughout the period to provide reasonable assurance that Northwind's service commitments and system requirements were achieved, except for the exceptions noted in Section 4.

Northwind AI, Inc. Management

---

## Section 3 — Description of the System

### Company Overview

Northwind AI, Inc. provides an enterprise generative-AI assistant ("Northwind Assistant") and a developer API ("Northwind API") that enable organizations to build applications on large language models with enterprise controls for data privacy, access management, and auditability. Northwind was founded in 2021 and is headquartered in Seattle, Washington.

### Services Provided

The System in scope comprises the production environment supporting Northwind Assistant (web application and enterprise administration) and Northwind API (developer platform), including model-serving infrastructure, the customer-facing applications, supporting data stores, and the internal tooling used to operate them.

### Infrastructure

The System is hosted primarily on Google Cloud Platform (GCP) in the us-central1 and us-east4 regions, with model-serving and failover capacity on Amazon Web Services (AWS) us-west-2. The EU region (europe-west1) is available for customers requiring EU data residency. Production services run as containerized workloads on Google Kubernetes Engine (GKE) and Amazon Elastic Kubernetes Service (EKS). Structured data is stored in managed PostgreSQL (Cloud SQL and Amazon RDS); object data is stored in Google Cloud Storage and Amazon S3.

### Software and Data

Customer data categories processed by the System include customer prompts and completions, uploaded files, account and identity data, usage metadata, and billing data. By default, enterprise and API customer content is not used to train Northwind's base models; training use is opt-in only. Cardholder data for billing is processed by a PCI-compliant payment processor (Stripe) and is not stored by Northwind.

### People

Northwind operates the System with engineering, security, GRC, IT, and customer-facing teams. A dedicated Security and Governance, Risk & Compliance organization, led by the CISO, is responsible for the security program. The CISO reports to the CTO.

### Control Environment Summary

- **Logical access** is role-based and least-privilege. Workforce identity uses Okta SSO with mandatory multi-factor authentication. Production access requires approval and is reviewed quarterly.
- **Encryption** protects customer data at rest (AES-256 via Cloud KMS / AWS KMS) and in transit (TLS 1.2+).
- **Change management** requires peer review, automated testing, and approval before deployment through CI/CD pipelines.
- **Operations** include continuous vulnerability scanning, 24/7 security monitoring, centralized logging, and a tested incident response plan.
- **Availability** is supported by capacity monitoring, tested backups, and multi-region failover (RTO 4h / RPO 1h for core services).
- **Privacy** aligns to ISO/IEC 27701; customer content is treated as confidential and is not used to train base models by default.

### Complementary User Entity Controls (CUECs)

The achievement of the trust services criteria requires user entities (customers) to implement certain controls. Northwind's controls were designed with the assumption that the following CUECs would be implemented by user entities:

1. User entities are responsible for configuring SSO/SCIM and enforcing MFA for their own users.
2. User entities are responsible for managing their own users' access and promptly removing access for terminated users within their tenant.
3. User entities are responsible for safeguarding API keys and credentials issued to them.
4. User entities are responsible for determining what data they submit in prompts and whether such data is appropriate for the service.
5. User entities are responsible for reviewing and configuring data-retention and training opt-in settings according to their requirements.

### Subservice Organizations

Northwind uses GCP and AWS as subservice organizations for hosting and compute and applies the carve-out method. The Description does not include the controls of these subservice organizations; relevant complementary subservice organization controls are assumed to be in place.

---

## Section 4 — Testing Matrices

The following presents the applicable trust services criteria, the controls specified by Northwind, the tests performed by Harbor Assurance LLP, and the results. "No exceptions noted" indicates the control operated effectively for the sample tested.

| Control # | Control Activity Specified by the Service Organization | Test Applied by the Service Auditor | Test Results |
|---|---|---|---|
| CC1.1 | A code of conduct is acknowledged by employees at hire and annually. | Inspected the code of conduct and acknowledgment records for a sample of employees to determine acknowledgments were obtained. | No exceptions noted. |
| CC1.4 | A security organization with defined roles reports to executive management. | Inspected the organizational chart and role descriptions to determine the security organization and reporting line existed. | No exceptions noted. |
| CC3.2 | Management performs a formal risk assessment at least annually. | Inspected the annual risk assessment to determine it was performed and risks were documented and tracked. | No exceptions noted. |
| CC6.1 | Production access is role-based, least-privilege, and protected by SSO with mandatory MFA. | Inspected the Okta configuration and a sample of access grants to determine access was role-based and MFA was enforced. | No exceptions noted. |
| CC6.2 | New access requires manager and system-owner approval before provisioning. | Inspected provisioning tickets for a sample of 25 access grants to determine approvals were obtained prior to provisioning. | No exceptions noted. |
| CC6.2.1 | Access for terminated employees is revoked within one business day of termination. | Inspected termination records and access-removal logs for a sample of 25 terminated employees to determine access was revoked within one business day. | **Exception noted.** For 2 of 25 sampled terminations, production access was revoked in four and five business days, respectively, exceeding the one-business-day policy. Management remediated the access and reinforced the offboarding procedure. |
| CC6.3 | Privileged and production access is reviewed quarterly and discrepancies remediated. | Inspected the four quarterly access reviews and remediation records for the period. | **Exception noted.** The Q3 2025 access review for one engineering team was completed 23 days after the quarter close, outside the defined quarterly cadence. The review was subsequently completed with no inappropriate access identified; management reinforced the review schedule. |
| CC6.6 | All external and internal service traffic is encrypted using TLS 1.2 or higher. | Inspected TLS configuration and scan results to determine TLS 1.2+ was enforced. | No exceptions noted. |
| CC6.7 | Customer data is encrypted at rest using AES-256. | Inspected encryption configuration for data stores to determine AES-256 encryption at rest was enabled. | No exceptions noted. |
| CC7.1 | Continuous vulnerability scanning is performed and findings triaged by severity SLA. | Inspected scanning tool configuration and a sample of findings to determine scans ran and findings were triaged within SLA. | No exceptions noted. |
| CC7.2 | Security events are centrally logged and monitored 24/7 with alerting. | Inspected logging/SIEM configuration and a sample of alerts to determine monitoring and alerting operated. | No exceptions noted. |
| CC7.4 | A documented incident response plan is maintained and tested at least annually. | Inspected the IR plan and the annual tabletop test results to determine the plan was maintained and tested. | No exceptions noted. |
| CC8.1 | Changes follow peer review, automated testing, and approval before deployment. | Inspected a sample of 25 change records to determine review, testing, and approval occurred before deployment. | No exceptions noted. |
| CC9.2 | Third parties are risk-assessed at onboarding and DPAs are obtained for processors of customer data. | Inspected vendor risk assessments and DPAs for a sample of subprocessors to determine assessments and DPAs existed. | No exceptions noted. |
| A1.2 | Backups are performed and capacity is monitored to support availability. | Inspected backup configuration and capacity monitoring to determine backups ran and capacity was monitored. | No exceptions noted. |
| A1.3 | Disaster recovery is tested at least annually against documented RTO/RPO. | Inspected the annual DR test results to determine recovery was tested against RTO/RPO objectives. | No exceptions noted. |
| C1.1 | Confidential data is classified and handled per policy. | Inspected the data classification policy and handling procedures to determine confidential data was classified. | No exceptions noted. |
| C1.2 | Confidential data is securely deleted at end of retention or upon customer request. | Inspected deletion procedures and a sample of deletion requests to determine data was deleted within the defined timeframe. | No exceptions noted. |
| P3.2 | Enterprise/API customer content is not used to train base models by default (opt-in only). | Inspected the data-use configuration and policy to determine customer content was excluded from base-model training by default. | No exceptions noted. |
| P6.1 | Processes support data subject and customer deletion/access requests within contractual timeframes. | Inspected a sample of requests to determine they were fulfilled within the defined timeframe. | No exceptions noted. |

---

## Section 5 — Other Information Provided by Management

### Management's Response to Exceptions

**CC6.2.1 (terminated access revocation).** Management investigated the two exceptions and confirmed no unauthorized activity occurred during the delay. The offboarding workflow was updated in Q4 2025 to trigger automated access removal upon HR status change, reducing reliance on manual steps.

**CC6.3 (quarterly access review timeliness).** Management completed the delayed Q3 2025 review with no inappropriate access identified. Calendar reminders and an owner were assigned to enforce the quarterly cadence going forward.

### Roadmap Items (not part of the audited controls)

- Customer-managed encryption keys (CMEK / BYOK): planned for H2 2026.
- Public bug bounty program: planned; a private vulnerability disclosure process is currently in place.
