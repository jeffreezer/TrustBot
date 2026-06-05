# Northwind AI — Logging & Monitoring Policy

> **SYNTHETIC / FICTIONAL demo document for TrustBot.** Consistent with the Northwind profile, controls, and SOC 2.
> **Owner:** CISO · **Version:** 2.0 · **Approved:** 2025-05-15 · **Review cadence:** Annual · **Next review:** 2026-05-15
> **Classification:** Internal — customer-shareable on request (NDA)
> **Related controls:** CC7.2, LOG (catalog)

## 1. Purpose

Define logging and monitoring practices that support detection, investigation, and accountability.

## 2. Scope

Production systems, security-relevant events, and administrative activity.

## 3. Policy

- **Centralized logging.** Security-relevant events are centrally collected (Datadog/SIEM).
- **Monitoring.** The environment is monitored **24/7** with alerting to an on-call security team.
- **Log integrity.** Logs are access-restricted and protected against tampering; access is itself logged.
- **No sensitive data in logs.** Secrets and customer/PII content must not be written to logs or error messages.
- **Time synchronization.** Systems are time-synchronized (NTP) for accurate event correlation.
- **Retention.** Logs are retained per the Data Retention & Deletion Policy.

## 4. Roles & Responsibilities

- **Security:** owns monitoring, detections, and alert response.
- **Engineering:** ensures services emit appropriate, sanitized logs.

## 5. Exceptions

Exceptions require documented approval from the CISO.
