# TrustBot — Full Vision & Roadmap (Everything Beyond the First Two Milestones)

> **Status:** Aspirational / preserved scope. This document keeps the broader vision intact so nothing from the original plan is lost. It is **not** the immediate build target.
> **Companion documents:** `01_TrustBot_MVP_Portfolio_Plan.md` (Milestone 1, build this first), `02_TrustBot_Vendor_Review_Component.md` (Milestone 2). The full original plan is retained verbatim as `trustbot_questionnaire_responder_project_plan.md`.

---

## 1. How the Pieces Fit Together

TrustBot is one shared engine — document parsing, retrieval + reranking, structured output, human-in-the-loop review, audit logging — pointed in three directions:

1. **Respond** (Milestone 1): answer inbound questionnaires from our own verified evidence.
2. **Review** (Milestone 2): assess vendors' completed questionnaires for third-party risk.
3. **Publish** (this doc): turn the same verified internal knowledge into outward-facing trust collateral — a security package and a trust center.

Everything in this document builds on the source-of-truth (company profile, control catalog, evidence vault, approved-answer library) created in Milestone 1. Nothing here should start until that foundation is solid and the first two milestones are finished and polished.

---

## 2. Recommended End-to-End Sequence

1. **Milestone 1 — Questionnaire Responder MVP** *(active; see doc 01)*
2. **Milestone 2 — Vendor Review / TPRM** *(next; see doc 02)*
3. **Milestone 3 — Trust Package Generator** *(this doc, §3)*
4. **Milestone 4 — Trust Center Microsite** *(this doc, §4)*
5. **Milestone 5 — Scale & Advanced Automation** *(this doc, §5)*
6. **Milestone 6 — Full TPRM Superset** *(this doc, §6)*

Each milestone should reach a finished, demonstrable state before the next begins. For a portfolio project especially, four polished milestones beat six half-built ones.

---

## 3. Milestone 3 — Trust Package Generator

Turn the verified internal knowledge base into a polished, customer-ready security package.

**Capabilities:**

- Wizard-style builder: select company/product profile → choose security domains → select approved, shareable evidence references → generate draft → review/edit → approve → export.
- Generates a structured security overview, a standard security FAQ, an evidence index, and a subprocessor list — all drawn only from approved, customer-shareable records.
- Output formats: Markdown and PDF first; later customer-specific packages and NDA-gated evidence rooms.

**Trust package content structure** (preserved from the original plan): security governance, infrastructure security, data protection, access control, secure development, monitoring & incident response, business continuity, vendor management, security FAQ, evidence index, subprocessor list, security contact.

**Guardrails:** the same evidence-first / no-fabrication / human-approval discipline as Milestone 1 — a generated package is a draft until a human approves it, and it must never include internal-only material or unevidenced claims.

---

## 4. Milestone 4 — Trust Center Microsite

A customer-facing portal that publishes approved security information and gates sensitive documents.

**Pages:** overview, security, privacy, compliance, subprocessors, FAQ, document request, contact.

**Access controls:** public pages, NDA-gated pages, customer-specific links, expiring document links, and download audit logs.

**Modernization note (updated assumption):** the original plan described a fairly *static* portal. The current expectation in this space is a **live / continuous** trust center — showing real-time or regularly-refreshed control status and evidence freshness rather than static PDFs. If this milestone is built, lean toward live status (pulling from the control catalog's review dates and evidence freshness) rather than a brochure. For a self-hosted open-source tool, "live" can simply mean the page reflects the current state of the knowledge base on each load.

---

## 5. Milestone 5 — Scale & Advanced Automation

Features that improve scale and quality once the core is proven:

- **Multi-tenant support.** Because every table already carries `org_id` (a deliberate Milestone 1 decision), this is an additive step rather than a rewrite: enforce `org_id` in every API authorization check, add Postgres row-level security, scope object-storage paths and vector retrieval by tenant, and carry tenant context through background jobs. Relevant if the project ever grows a hosted instance; optional for a pure self-host tool.
- **SIG / CAIQ native *export*** (us producing SIG/CAIQ-formatted outputs from our answers); portal-ready answer blocks; API output. *(Ingesting vendor-provided SIG/CAIQ submissions is a different, buyer-side concern and belongs to Milestone 2 — see doc 02 §5.1.)*
- **PDF/Word parsing depth** beyond the MVP for our own responder workflow. *(Reading vendor-provided compliance documents — SOC 2, pen test, PCI AOC, policies — is Milestone 2 scope, doc 02 §5.1, not here.)*
- **Browser extension** for capturing *inbound* portal-based questionnaires (responder-side), and (human-gated) one-click portal completion. Note: competitors ship this today; browser-agent tooling makes it feasible far earlier than the original plan assumed — but keep actual *submission* behind a human.
- **Evidence freshness automation:** expiration tracking, review reminders, stale-evidence warnings.
- **Framework mapping automation:** SOC 2 TSC, ISO 27001/27002, NIST CSF, NIST 800-53, CIS, CSA CAIQ/CCM, SIG, plus GDPR/HIPAA/PCI areas where relevant — to reuse control knowledge across questionnaire types.
- **Answer-library intelligence:** track where answers were used, surface drift, flag answers needing re-review.
- **Reviewer assistant mode, SSO/SCIM, customer-specific answer tone, redaction assistant, watermarked downloads, readiness/trust score.**

---

## 6. Milestone 6 — Full TPRM Superset

Milestone 2 delivers the core of buyer-side vendor review. The original "TrustBot" third-party-risk vision extends well beyond it; preserved here as the long-tail:

- Internal vendor intake form and vendor classification.
- High/Medium/Low **risk tiering** driving questionnaire selection.
- Tiered questionnaire generation.
- **Vendor-facing portal** for self-service completion.
- Trust-portal discovery and document retrieval (auto-pull a vendor's published trust center).
- **OSINT search and breach-database checks** against vendors.
- **LLM-based threat modeling** with Mermaid diagram generation.
- Final assessment report synthesis with human sign-off.
- Continuous vendor monitoring, periodic re-assessment scheduling, and **vendor risk scorecards over time**.
- Portfolio-level dashboards: visual risk map, risk forecasting, SLA escalation, multi-team review.

These are genuinely later-stage and should not distort the near-term build.

---

## 7. Other Future Enhancements (Parking Lot)

Preserved from the original plan so they aren't lost: continuous monitoring, automated policy-compliance checks, AI anomaly detection in answers, shared secrets vault, vendor identity validation, chain-of-trust mapping, self-audit mode, executive summaries, evidence-retention policy, versioned assessment history, live questionnaire API integrations with procurement portals.

Most of these belong to the mature product, not any near-term milestone. Capture ideas here; don't let them pull focus from finishing Milestones 1 and 2.

---

## 8. Architecture Notes That Carry Across All Milestones

- **Self-hostable and vendor-neutral by default** (fully open source; data never has to leave the operator's infrastructure). Model access stays behind a provider-abstraction layer; storage behind an S3-compatible adapter.
- **`org_id` on every table from day one**, even while single-tenant, so multi-tenant is additive.
- **Untrusted input is a security boundary** in every direction — our uploads, vendor submissions, published-page inputs. Prompt-injection defenses and output validation are non-negotiable.
- **Evidence-first, no fabrication, human-approval-before-external-use, version-everything, immutable audit log** — the same five disciplines apply whether we're responding, reviewing, or publishing.

---

## 9. Cross-Reference Map

| Concern | Lives in |
|---|---|
| Source of truth (profile, controls, evidence, answer library) | Milestone 1 — doc 01 |
| Agentic retrieval + reranking + evals + injection defense | Milestone 1 — doc 01 |
| Responding to inbound questionnaires | Milestone 1 — doc 01 |
| Reviewing vendors' returned questionnaires (TPRM core) | Milestone 2 — doc 02 |
| Ingesting & reviewing vendor compliance docs (SOC 2, pen test, PCI AOC, SIG/CAIQ submissions, policies) | Milestone 2 — doc 02 §5.1 |
| Defensible findings, risk scoring, audit/report layer | Milestone 2 — doc 02 |
| Trust package generation | Milestone 3 — this doc §3 |
| Trust center microsite (live) | Milestone 4 — this doc §4 |
| Multi-tenant, SIG/CAIQ, browser capture, framework mapping | Milestone 5 — this doc §5 |
| OSINT, breach search, threat modeling, vendor portal, monitoring | Milestone 6 — this doc §6 |
