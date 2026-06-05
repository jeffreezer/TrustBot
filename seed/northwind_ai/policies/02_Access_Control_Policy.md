# Northwind AI — Access Control Policy

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the Northwind profile, control catalog, and SOC 2.
> **Owner:** CISO · **Version:** 2.0 · **Approved:** 2025-05-15 · **Review cadence:** Annual · **Next review:** 2026-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** CC6.1, CC6.2, CC6.3, IAM (catalog)

## 1. Purpose

Define how access to Northwind systems and customer data is granted, reviewed, and revoked.

## 2. Scope

All production systems, internal tools, and data stores across GCP and AWS, and all workforce and service identities.

## 3. Policy

- **Least privilege & RBAC.** Access is role-based and granted on the principle of least privilege. Standing access to production is minimized.
- **Authentication.** Workforce identity is federated through Okta SSO with **mandatory multi-factor authentication (MFA)** for all users, including privileged access.
- **Provisioning.** New or changed access requires manager and system-owner approval through a ticketed workflow before it is granted.
- **Privileged access.** Administrative actions use just-in-time elevation with approval; privileged sessions are logged.
- **Access reviews.** Privileged and production access is reviewed **quarterly**; discrepancies are remediated and the review is recorded.
- **Deprovisioning.** Access is revoked promptly upon role change or termination; policy target is one business day, supported by automated removal triggered on HR status change.
- **Customer access.** Northwind Enterprise supports customer SSO (SAML/OIDC) and SCIM; customers are responsible for enforcing MFA and managing their own users (a complementary user-entity control).

## 4. Roles & Responsibilities

- **Security/IT:** administers identity, provisioning, and reviews.
- **System owners:** approve access to their systems.
- **Managers:** approve and periodically attest to team access.

## 5. Exceptions

Exceptions require documented risk acceptance approved by the CISO.
