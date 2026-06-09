# TrustBot — Production Readiness & Known Gaps

> **Status: living document.** An honest map of what is production-shaped today versus what an organization would need before relying on TrustBot for real, external-facing questionnaire responses. Written to be read by adopters and reviewers — for a security/GRC audience, knowing exactly where the edges are is more credible than a polished surface.
> **Companion documents:** `08_TrustBot_Source_Connectors.md`, `05_TrustBot_Respond_Mode_Design.md` (§11 auth sequencing), `SECURITY.md`, `04_TrustBot_MVP_Build_Guide.md`.

---

## 1. What Is Production-Shaped Today

The **answering engine** is built and hardened:

- Evidence-first answering grounded in approved, org-owned evidence; structured claim/attestation model (`07`); explicit `needs_input` instead of guessing.
- Hybrid retrieval (pgvector + Postgres FTS) + reranking; adaptive retrieval loop with multi-part decomposition.
- Deterministic output validators; composite confidence; human-in-the-loop review before anything is external; audit log throughout.
- Document disclosure via an authenticated, org-scoped, audited download path (layer 1).
- Prompt-injection defense (four layers, per-posture) with an adversarial suite gating CI; documented threat model in `SECURITY.md`.
- An offline eval gate in CI (faithfulness / overclaiming as categorical hard-fails).
- `org_id` scoping on every table and route from day one; cloud-portable (GCP / AWS) via env config.

This is the hard part, and it is done. The gaps below are the **onboarding, access, and operational layers** between "runs on a curated demo" and "our team uses it on real data."

---

## 2. Gaps Before Real-Org Use

### 2.1 Authentication & multi-user — *tracked in `05` §11*
**State:** single-org seam (`get_current_org`), no login. Fine for one operator on a trusted machine; not for a team or a reachable URL.
**Needed:** IAP at the edge (quick first identity) → app login + roles/RBAC (reviewer/approver/admin) → full multi-tenant auth (identity drives org). The org-scoping already exists, so auth plugs into the seam rather than requiring a rewrite.

### 2.2 Evidence onboarding & source connectors — *designed in `08`*
**State:** the only ingestion path is the `seed.py` loader pointed at a directory of files. There is no self-service way for an org to load its own evidence corpus.
**Needed:** the Source Connectors work (`08`) — curated Google Drive / Confluence ingestion and Glean-as-discovery, or an evidence-upload admin UI. This is the single highest-value real-use gap.

### 2.3 Real-document robustness — *partially noted (`04`:tooling)*
**State:** ingestion and the certification extractor are tuned to clean, structured (markdown) documents. Real evidence is PDFs, sometimes scanned.
**Needed:** robust PDF/scanned-document parsing (PyMuPDF + a multimodal-model fallback, per the build guide), and the **model-assisted + human-confirmed** version of `extract_attested_certifications` so "which certifications does this certificate cover" is reliable on messy real-world attestations (today's extractor is deterministic and seed-shaped).

### 2.4 Cloud background-execution model — *flagged during the async-jobs work*
**State:** answer generation runs as an in-process async job; on Cloud Run, CPU is throttled after the response returns, so background drafting can stall.
**Needed:** for a real cloud deployment, either CPU-always-allocated + `min-instances ≥ 1`, or move generation to a Cloud Run Job / task queue.

### 2.5 External document delivery — *trust-center scope (`05` §8.3)*
**State:** documents are served via an authenticated, org-scoped endpoint (no bearer links). There is no external-recipient delivery.
**Needed:** recipient magic-link + email infrastructure, per-recipient grants, and watermarking/view-only — the trust-center milestone.

### 2.6 Standard production operations — *not yet addressed*
Rate limiting at the edge, observability/monitoring/alerting, database backup/restore policy, secret rotation runbook, and dependency hash-locking (supply-chain reproducibility; noted in the security-audit follow-ups). None are blockers for the engine; all are table stakes for a production service.

---

## 3. Intentional Constraints (Not Gaps)

These are by design, not omissions:

- **Human review is required before any answer is external.** The system drafts; a person approves. This is the core safety property, not a limitation to "automate away."
- **Single-tenant now.** `org_id` is on every table so multi-tenant is additive, but isolation hardening is deferred deliberately.
- **Approved-answer reuse is a candidate, not a bypass** — reused answers are re-validated against current evidence.
- **The blocking CI gate is offline/deterministic;** real-model evals run out-of-band (cost + nondeterminism), by choice.

---

## 4. How To Read This

If you are evaluating TrustBot for real use: the **reasoning, grounding, and safety machinery is ready**; the **identity, evidence-onboarding, and ops layers are the work between a strong demo and a deployed service.** Sections 2.1–2.3 are the critical path for a single team to start using it on real questionnaires; 2.4–2.6 follow for a hardened, externally-facing deployment.
