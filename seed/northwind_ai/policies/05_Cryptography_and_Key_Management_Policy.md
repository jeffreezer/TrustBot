# Northwind AI — Cryptography & Key Management Policy

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the Northwind profile, controls, and SOC 2.
> **Owner:** VP Engineering · **Version:** 2.0 · **Approved:** 2025-05-15 · **Review cadence:** Annual · **Next review:** 2026-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** CC6.6, CC6.7, CC6.8, CEK (catalog)

## 1. Purpose

Define cryptographic standards and key management practices.

## 2. Scope

All Northwind systems and data stores handling customer or sensitive data.

## 3. Policy

- **Encryption at rest.** Customer data is encrypted at rest using **AES-256**.
- **Encryption in transit.** All external and internal service-to-service traffic uses **TLS 1.2 or higher**.
- **Key management.** Keys are managed in **Google Cloud KMS** and **AWS KMS** using envelope encryption. Keys are access-controlled, rotated on a defined schedule, and never embedded in code or logs.
- **Customer-managed keys (CMEK / BYOK).** **Not currently supported.** Encryption uses Northwind-managed keys today; CMEK is on the roadmap for **H2 2026**.
- **Approved algorithms.** Only vetted, industry-standard cryptographic libraries and algorithms are used. Proprietary/"home-grown" cryptography is prohibited.

## 4. Roles & Responsibilities

- **Engineering:** implements and operates encryption and key management.
- **Security:** reviews cryptographic standards annually.

## 5. Exceptions

Exceptions require documented risk acceptance approved by the CISO.
