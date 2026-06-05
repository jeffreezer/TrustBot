# Northwind AI — Secure Software Development (SDLC) Policy

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the Northwind profile, controls, and SOC 2.
> **Owner:** VP Engineering · **Version:** 2.0 · **Approved:** 2025-05-15 · **Review cadence:** Annual · **Next review:** 2026-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** CC8.1, SDLC1.1

## 1. Purpose

Integrate security into every stage of the software development lifecycle.

## 2. Scope

All Northwind application and infrastructure code.

## 3. Policy

- **Secure design.** Security requirements and threat considerations are addressed during design.
- **Code review.** All changes require peer review before merge.
- **Automated testing.** Static (SAST) and dynamic (DAST) application security testing and dependency/vulnerability scanning run in CI/CD; findings are triaged by severity SLA.
- **Approval & deployment.** Changes are tested and approved before deployment through controlled CI/CD pipelines (see Change Management Policy).
- **Separation of duties.** The author of a change and its approver are different individuals.
- **Secrets.** No secrets in source code; secrets are managed via GCP Secret Manager / AWS Secrets Manager.
- **Developer training.** Developers receive secure-coding training.

## 4. Roles & Responsibilities

- **Engineering:** implements secure development practices.
- **Security:** defines standards and reviews tooling.

## 5. Exceptions

Exceptions require documented approval from the VP Engineering.
