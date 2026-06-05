# Northwind AI — Vendor / Third-Party Risk Management Policy

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the Northwind profile, controls, and SOC 2.
> **Owner:** Head of GRC · **Version:** 2.0 · **Approved:** 2025-05-15 · **Review cadence:** Annual · **Next review:** 2026-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** CC9.2, STA (catalog)

## 1. Purpose

Define how Northwind assesses and manages risk from third parties (subprocessors and vendors).

## 2. Scope

All third parties that process Northwind or customer data or provide critical services.

## 3. Policy

- **Risk assessment at onboarding.** Vendors are assessed for security before onboarding; depth scales with risk and data access.
- **Data protection agreements.** A DPA is required for any processor handling customer data.
- **Periodic review.** Critical vendors are reassessed periodically based on risk.
- **Subprocessor transparency.** A current subprocessor list is published at trust.northwind.ai/subprocessors; customers may subscribe to change notifications.
- **Key subprocessors.** Include Google Cloud and AWS (hosting), Cloudflare (CDN/WAF), Datadog (monitoring), Okta (identity), and Stripe (billing).

## 4. Roles & Responsibilities

- **GRC:** owns the vendor risk program and assessments.
- **Procurement/Engineering:** route new vendors through assessment before use.

## 5. Exceptions

Onboarding a vendor without completed assessment requires documented risk acceptance from the Head of GRC.
