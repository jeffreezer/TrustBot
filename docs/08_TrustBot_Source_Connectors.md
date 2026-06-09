# TrustBot — Source Connectors (Real-Org Evidence Onboarding)

> **Status: DESIGN / future work** (not built). How a real organization gets its own evidence into TrustBot, replacing the synthetic seed loader. This is the highest-value real-use gap: the answering engine is built, but the path for an org to onboard *its own* approved evidence is not.
> **Companion documents:** `07_TrustBot_Claim_Attestation_Model.md` (evidence-grounded principle), `05_TrustBot_Respond_Mode_Design.md` (document handling), `02_TrustBot_Vendor_Review_Component.md` (review mode, which ingests *untrusted* vendor docs — a different trust posture), `09_TrustBot_Production_Readiness.md`, `CLAUDE.md`.

---

## 1. The Problem

TrustBot answers from an ingested, org-scoped evidence corpus (parse → chunk → embed → pgvector, with document-kind classification, attested-cert extraction, and shareability tagging). That pipeline is built and solid. What is **not** built is a real way for an org to load *its own* corpus: today the only mechanism is `seed.py` pointed at a directory of synthetic Northwind files. A real org keeps its evidence in systems like Google Drive and Confluence (and often has an enterprise search layer like Glean over them).

This document specifies how that evidence flows in, **without breaking the evidence-first guarantee.**

---

## 2. The One Principle That Governs Everything Here

**Only approved, curated evidence may become an answer basis.** GDrive, Confluence, and Glean index *everything* — drafts, stale runbooks, internal debate, wikis of varying quality. Pointing TrustBot at "all of it" reintroduces the exact failure mode the product exists to prevent: drafting a customer-facing security attestation from an unvetted or out-of-date internal document. So every connector must be **scoped to a curated, approved subset**, and ingested content remains subject to the same shareability gating, injection screening, and human review as everything else. Curation is a feature, not a chore (see `07` §5: evidence-grounded, never self-asserted, no demo-fitting).

---

## 3. Two Patterns (Use Both)

### 3.1 Curated ingestion — the authoritative basis

Build connectors that pull from a **specific approved scope** (a designated Confluence space, a designated Drive folder of policies/reports/prior answers) and run the documents through the existing ingestion pipeline. The org keeps every guarantee: hybrid retrieval + reranking, the claim/attestation model, composite confidence, validators, `customer_shareable` gating, precise citations, and the audit trail. This is the primary path and the source of truth.

### 3.2 Glean as a scoped discovery source — the complement

Rather than rebuild a connector for every system, call Glean's permission-aware **Search API** (`developers.glean.com`; official Python/TS clients) from inside the **adaptive retrieval loop** — but only to *surface candidate evidence* when the curated corpus comes up short, scoped to approved collections via Glean's filters. Anything Glean surfaces is treated as a **candidate for human review and approval into the curated corpus, never an auto-emitted answer.** This maps onto existing patterns: `needs_input → human`, and "approved-answer reuse is a candidate, not a bypass." So Glean *discovers*; a human *blesses*; the curated corpus stays the authority.

---

## 4. Connector Mechanics

Each connector is **read-only** and **scoped**, behind a common "source connector" interface (consistent with the provider/storage abstractions):

- **Google Drive** — Drive API via a service account scoped to a specific folder (or OAuth); export Google Docs to text/markdown; record source URL + revision for provenance and freshness.
- **Confluence** — Confluence REST API (Cloud or Data Center); pull pages from named spaces; carry page metadata (space, version, last-updated).
- **Glean** — Search API as a query-time retrieval/discovery backend (§3.2), scoped to approved collections; results carry source links for citation.

Each ingested item flows through the existing pipeline: `document_kind` classification, `extract_attested_certifications` (so an ingested ISO certificate makes ISO "held" — evidence-derived, per `07`), `customer_shareable`/classification tagging, the Phase 8 injection screen, and chunk/embed.

---

## 5. Permissions & Governance

- **ACLs flatten on ingest.** GDrive/Confluence documents have per-user access controls; Glean respects them per user. Once ingested into TrustBot's single org-scoped store, those ACLs collapse into one corpus. Therefore **only ingest documents appropriate as shareable evidence**, and lean on the `customer_shareable` gate. Do not bulk-sync a whole Drive.
- **Identity/scope of access.** Decide what identity connectors run under (a service account scoped to approved content vs. per-user context).
- **This is a data-governance decision, not just engineering.** Which spaces/folders/collections count as "approved evidence" is a call for the org's security/GRC team, since the output is external-facing attestations.
- **Secrets** (connector credentials, Glean token) live in the secret manager, never in config or logs (CLAUDE.md).

---

## 6. Sync & Freshness

Connectors sync on a schedule (and/or on-demand). Each ingested item records its source, revision, and last-sync time so the existing **freshness** signal can flag stale citations (e.g. an attestation past its period). Re-ingesting an updated document supersedes the prior version (reuse the supersede pattern). Removing a source document removes its grounding — which is the correct, evidence-first behavior (`07` §5).

---

## 7. Relationship to Review Mode (Milestone 2)

These connectors onboard the **responding org's own, trusted** evidence. Milestone 2 (vendor review) ingests a **vendor's untrusted** submission, where the posture is quarantine-first injection defense and critical evaluation, not affirmation. Same ingestion plumbing, opposite trust assumption. Keep the two clearly separated.

---

## 8. Sequencing

This is a distinct **connectors milestone**. For an org actually adopting TrustBot it is arguably higher-value than Milestone 2/3, because it is the difference between "runs on a curated demo" and "runs on our real evidence." Recommended order: curated Drive/Confluence ingestion first (the authoritative path), Glean discovery second (the complement), with the permissions/governance guardrails of §5 from day one.
