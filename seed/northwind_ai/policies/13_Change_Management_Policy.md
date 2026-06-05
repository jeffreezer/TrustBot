# Northwind AI — Change Management Policy

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the Northwind profile, controls, and SOC 2.
> **Owner:** VP Engineering · **Version:** 2.0 · **Approved:** 2025-05-15 · **Review cadence:** Annual · **Next review:** 2026-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** CC8.1

## 1. Purpose

Ensure changes to production are made in a controlled, reviewed, and reversible manner.

## 2. Scope

All changes to production application code and infrastructure.

## 3. Policy

- **Review & approval.** Changes require peer review and approval before deployment.
- **Testing.** Automated tests run before release; deployments go through controlled CI/CD pipelines.
- **Separation of duties.** The author and approver of a change are different individuals.
- **Rollback.** Changes are designed to be reversible; automated rollback is available for failed deployments.
- **Emergency changes.** Emergency changes follow an expedited but documented process and are reviewed retrospectively.
- **Traceability.** Changes are tracked and auditable.

## 4. Roles & Responsibilities

- **Engineering:** authors, reviews, and deploys changes.
- **Security:** reviews security-relevant changes.

## 5. Exceptions

Exceptions require documented approval from the VP Engineering.
