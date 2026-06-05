# Northwind AI — Data Classification & Handling Policy

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the Northwind profile, controls, and SOC 2.
> **Owner:** Head of GRC · **Version:** 2.0 · **Approved:** 2025-05-15 · **Review cadence:** Annual · **Next review:** 2026-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** C1.1, C1.2, DSP (catalog)

## 1. Purpose

Establish how Northwind classifies and handles data according to sensitivity.

## 2. Scope

All data created, processed, or stored by Northwind, including customer content.

## 3. Classification Tiers

- **Public** — intended for public release (e.g., marketing, the security whitepaper).
- **Internal** — internal business information; not for external release without approval.
- **Confidential** — customer content, credentials, and sensitive business data. Customer prompts, completions, and uploaded files are classified Confidential by default.
- **Restricted** — secrets, encryption keys, and regulated data; access tightly restricted and logged.

## 4. Handling Requirements

- Confidential and Restricted data is encrypted at rest (AES-256) and in transit (TLS 1.2+).
- Access follows the Access Control Policy (least privilege, MFA).
- Customer content is not used to train Northwind base models by default (opt-in only).
- Data is retained and deleted per the Data Retention & Deletion Policy.
- Confidential data must not be placed in logs, error messages, or tickets.

## 5. Roles & Responsibilities

- **Data owners:** assign classification.
- **All personnel:** handle data per its classification.

## 6. Exceptions

Exceptions require documented approval from the Head of GRC.
