# Northwind AI — Company Security Profile

> **SYNTHETIC / FICTIONAL.** Northwind AI is an invented company created as demo and test data for TrustBot. Any resemblance to a real company is coincidental. This file is the source-of-truth profile that seeds the system; every other Northwind document is consistent with it.

## Company Basics

| Field | Value |
|---|---|
| Legal name | Northwind AI, Inc. |
| Product names | Northwind Assistant (enterprise AI chat) and Northwind API (developer platform) |
| Description | Northwind AI provides an enterprise generative-AI assistant and a developer API that let organizations build on large language models with enterprise controls for data privacy, access, and auditability. |
| Founded | 2021 |
| Headquarters | Seattle, Washington, USA |
| Ownership | Privately held |
| Employees | ~480 |
| Website | northwind.ai (fictional) |
| Security contact | security@northwind.ai |
| Privacy contact | privacy@northwind.ai |
| Trust center | trust.northwind.ai (fictional) |

## Infrastructure & Hosting

| Field | Value |
|---|---|
| Primary cloud | Google Cloud Platform (GCP) — us-central1, us-east4 |
| Secondary cloud | Amazon Web Services (AWS) — us-west-2 (model serving, failover) |
| Production regions | United States (primary). EU (europe-west1) available for EU data-residency customers. |
| Model hosting | GPU clusters on GCP and AWS; no customer prompt data used to train base models by default. |
| Architecture | Containerized microservices on GKE (GCP) and EKS (AWS); managed Postgres (Cloud SQL / RDS); object storage on GCS and S3. |
| CDN / edge | Cloudflare |

## Data Handling

| Field | Value |
|---|---|
| Customer data categories | Customer prompts and completions, uploaded files, account/identity data, usage metadata, billing data. |
| Sensitive data | Customers may submit confidential business data; Northwind does not require or solicit PHI/PCI cardholder data in prompts. Billing handles cardholder data via a PCI-compliant processor. |
| Training use | Enterprise/API customer content is NOT used to train base models by default; opt-in only. |
| Encryption at rest | AES-256 (GCS/S3, Cloud SQL/RDS, disk-level). |
| Encryption in transit | TLS 1.2+ for all external and internal service-to-service traffic. |
| Key management | Cloud KMS (GCP) and AWS KMS; envelope encryption. Customer-managed keys (CMEK): **not yet supported — on roadmap.** |
| Data retention | Enterprise customer content retained per contract; default 30-day retention for abuse-monitoring logs, then deleted. Customers can request deletion. |
| Data deletion | Tenant data deleted within 30 days of contract termination. |

## Identity, Access & Security Tooling

| Field | Value |
|---|---|
| Workforce identity | Okta SSO with mandatory MFA (WebAuthn/TOTP). |
| Customer authentication | SSO (SAML/OIDC) and SCIM for Enterprise; API key auth for the API platform. |
| Privileged access | Just-in-time elevation with approval; quarterly access reviews. |
| Endpoint security | Managed devices with MDM, disk encryption, EDR (CrowdStrike). |
| Logging/monitoring | Centralized logging (Datadog), SIEM, 24/7 on-call security. |
| Vulnerability mgmt | Continuous scanning (containers, dependencies, infra); annual third-party penetration test. |
| Secrets management | GCP Secret Manager / AWS Secrets Manager; no secrets in code. |

## Governance, Compliance & Certifications

| Field | Value |
|---|---|
| Frameworks | SOC 2 Type 2 (Security, Availability, Confidentiality, Privacy); ISO/IEC 27001, 27017, 27018, 27701; PCI DSS (Service Provider, billing scope). |
| SOC 2 period | January 1, 2025 – December 31, 2025 (Type 2). |
| SOC 2 auditor | Harbor Assurance LLP (fictional). |
| Penetration tester | Ridgeline Security (fictional). |
| GRC function | Dedicated Governance, Risk & Compliance team; CISO reports to the CTO. |
| Incident response | Documented IR plan; security incident owner; customer notification per contract/SLA. |
| BCP/DR | Multi-region failover; backups tested; documented RTO 4h / RPO 1h for core services. |

## Subprocessors (summary)

| Subprocessor | Purpose | Data | Region | DPA |
|---|---|---|---|---|
| Google Cloud (GCP) | Primary hosting & compute | All customer data categories | US, EU | Yes |
| Amazon Web Services | Model serving & failover | Prompts/completions | US | Yes |
| Cloudflare | CDN / DDoS / WAF | Metadata, traffic | Global | Yes |
| Datadog | Logging & monitoring | Operational logs (may contain metadata) | US | Yes |
| Okta | Workforce identity | Employee identity | US | Yes |
| Stripe | Billing / payment processing | Cardholder data | US | Yes |
| Anthropic/OpenAI model APIs | (n/a — Northwind serves its own models) | — | — | — |

> Full, current subprocessor list published at trust.northwind.ai/subprocessors.
