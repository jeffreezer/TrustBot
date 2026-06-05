# Northwind AI — Data Retention & Deletion Policy

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the Northwind profile, controls, and SOC 2.
> **Owner:** DPO · **Version:** 2.0 · **Approved:** 2025-05-15 · **Review cadence:** Annual · **Next review:** 2026-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** C1.2, P6.1, DSP (catalog)

## 1. Purpose

Define how long Northwind retains data and how it is securely deleted.

## 2. Scope

All customer content, account data, operational logs, and backups.

## 3. Policy

- **Customer content.** Retained for the duration of the customer relationship per contract. Customers may request deletion at any time.
- **Termination.** Tenant data is deleted within **30 days** of contract termination.
- **Abuse-monitoring logs.** Retained for a default of **30 days**, then deleted, unless a longer period is contractually agreed.
- **Backups.** Encrypted and retained per the Business Continuity & DR Plan; expired backups are securely destroyed.
- **Deletion method.** Deletion is performed through controlled processes; storage is cryptographically and/or logically erased so data is not recoverable.
- **Data subject / customer requests.** Access and deletion requests are fulfilled within contractual timeframes (see Privacy & Data Protection Policy).

## 4. Roles & Responsibilities

- **DPO:** owns retention schedules and data-subject request handling.
- **Engineering:** implements deletion and retention controls.

## 5. Exceptions

Legal hold may suspend deletion; exceptions are documented and approved by the DPO and Legal.
