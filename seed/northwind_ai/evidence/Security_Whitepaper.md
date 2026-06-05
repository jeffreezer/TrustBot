# Northwind AI — Security Whitepaper

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** A customer-facing security overview consistent with the Northwind company profile and audited controls.

## Overview

Northwind AI provides an enterprise generative-AI assistant (Northwind Assistant) and a developer API (Northwind API). Security and privacy are foundational to the platform. This whitepaper summarizes how Northwind protects customer data across infrastructure, access, encryption, development, operations, and privacy.

## Infrastructure Security

Northwind runs on Google Cloud Platform (primary) and Amazon Web Services (secondary/failover) in the United States, with an EU region available for data-residency customers. Production services run as containerized workloads on GKE and EKS with network segmentation, security groups, and a Cloudflare web application firewall. Infrastructure is defined as code and configured against hardened baselines, with cloud security posture monitoring.

## Data Protection and Encryption

All customer data is encrypted at rest using AES-256 and in transit using TLS 1.2 or higher. Encryption keys are managed in Cloud KMS and AWS KMS using envelope encryption. Customer-managed encryption keys (CMEK/BYOK) are on the roadmap for H2 2026; today, encryption uses Northwind-managed keys.

## Identity and Access Management

Workforce access is role-based and least-privilege, secured by Okta SSO with mandatory multi-factor authentication. Production access requires approval and is reviewed quarterly. Just-in-time elevation is used for privileged operations. For customers, Northwind Enterprise supports SSO (SAML/OIDC) and SCIM provisioning; the API platform uses scoped API keys.

## Secure Development

Security is integrated throughout the software development lifecycle. Changes require peer review, automated testing, and approval before deployment via CI/CD. Static and dynamic application security testing (SAST/DAST) and dependency scanning run automatically, and findings are triaged against severity-based SLAs.

## Operations, Monitoring, and Incident Response

Security events are centrally logged and monitored 24/7 with alerting to an on-call security team. Northwind maintains a documented incident response plan defining roles, severity levels, communications, and customer notification, and tests it at least annually. Customers are notified of incidents affecting their data in accordance with their contract and SLA.

## Vulnerability Management

Northwind performs continuous vulnerability scanning across containers, dependencies, and infrastructure, and engages an independent firm for a penetration test at least annually. Findings are tracked to remediation by severity. A private vulnerability disclosure process is available at security@northwind.ai; a public bug bounty program is planned.

## Availability and Resilience

Capacity is monitored and backups are performed and tested. Multi-region failover supports availability commitments, with documented objectives of RTO 4 hours and RPO 1 hour for core services. A business continuity plan is reviewed annually.

## Privacy and Data Use

Northwind's privacy program aligns to ISO/IEC 27701. Enterprise and API customer content is not used to train Northwind's base models by default; training use is strictly opt-in. Customer content is treated as confidential, and Northwind supports data deletion and data-subject requests within contractual timeframes. Tenant data is deleted within 30 days of contract termination.

## Compliance

Northwind maintains SOC 2 Type 2 (Security, Availability, Confidentiality, Privacy); ISO/IEC 27001, 27017, 27018, and 27701; and PCI DSS (Service Provider) for its billing scope. Reports and certificates are available under NDA via the Northwind Trust Center at trust.northwind.ai.
