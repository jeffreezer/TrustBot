# Northwind AI — Business Continuity & Disaster Recovery Plan

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the Northwind profile, controls, and SOC 2.
> **Owner:** VP Engineering · **Version:** 2.0 · **Approved:** 2025-05-15 · **Review cadence:** Annual (tested annually) · **Next review:** 2026-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** A1.2, A1.3, BC1.1

## 1. Purpose

Ensure Northwind can continue critical operations and recover services after a disruption.

## 2. Scope

Core production services supporting Northwind Assistant and Northwind API.

## 3. Objectives

- **Recovery Time Objective (RTO):** 4 hours for core services.
- **Recovery Point Objective (RPO):** 1 hour for core services.

## 4. Policy

- **Resilience.** Services run across multiple GCP regions with AWS failover capacity; architecture avoids single points of failure.
- **Backups.** Data is backed up regularly, encrypted at rest, and **restoration is tested**.
- **DR testing.** Disaster recovery is tested at least **annually** against the RTO/RPO objectives.
- **Continuity.** A business continuity plan covers critical functions and is reviewed annually.
- **Communications.** Customer-impacting disruptions are communicated per SLA.

## 5. Roles & Responsibilities

- **Engineering/SRE:** owns backups, failover, and DR testing.
- **Leadership:** approves continuity priorities.

## 6. Exceptions

Exceptions to backup/DR standards require documented approval from the VP Engineering.
