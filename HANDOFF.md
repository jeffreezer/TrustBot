# TrustBot — Handoff for Claude Code

Read this first. It orients you (Claude Code) to the project, points you at the source-of-truth docs, and tells you what to build next. When in doubt, the planning docs below are authoritative.

## What this is

TrustBot is an **evidence-backed AI security questionnaire responder**: it drafts answers to security questionnaires using only a company's verified, approved evidence, and **flags anything it cannot support for human review instead of guessing**. It's a **fully open-source (MIT), self-hostable** project, built primarily as a portfolio/proof-of-work piece — so code quality, tests, evals, clear docs, and a one-command demo matter as much as features.

The owner runs his instance on **GCP**, wants **AWS portability**, and the project must stay self-hostable. Keep everything cloud-agnostic and containerized.

## Repository map

| Path | What it is |
|---|---|
| `01_TrustBot_MVP_Portfolio_Plan.md` | Milestone 1 scope, principles, definition of done. **The spec for what you're building.** |
| `02_TrustBot_Vendor_Review_Component.md` | Milestone 2 (vendor review / inverse). Not yet — future. |
| `03_TrustBot_Full_Vision_Roadmap.md` | Everything beyond M1/M2. Future. |
| `04_TrustBot_MVP_Build_Guide.md` | **The step-by-step build guide. Follow its phases.** Stack rationale, repo structure, done-criteria per phase. |
| `05_TrustBot_Respond_Mode_Design.md` | **FINALIZED course correction — authoritative for Milestone 1 answer generation.** Respond-mode posture (affirm-and-cite, SOC 2 exception suppression, perspective resolution), outcome taxonomy, remediation register, document access (layer 1 + audit), auth sequencing. **Supersedes `04` where they conflict on drafting/classification.** |
| `06_TrustBot_Adaptive_Retrieval_Loop.md` | **FINALIZED Phase 6 design — authoritative for the agentic upgrade.** Single bounded agent, read-only org-scoped tools, deterministic validators unchanged, audited; shared engine for respond (M1, first) + review (M2). |
| `seed/northwind_ai/` | Synthetic demo data: fictional "Northwind AI" company profile, control catalog, evidence docs (SOC 2, pen test, AOC, ISO/SoA, whitepaper), completed CAIQ + an original security questionnaire. |
| `seed/northwind_ai/README.md` | **Answer key** for the seed data, incl. 9 deliberately planted traps with correct answers — the basis for the eval golden set. |
| `seed/northwind_ai/eval_golden_set.yaml` | Starter eval set wired to the traps. |
| `trustbot/` | The code. **Phase 0 scaffold is done and runs.** |

## Non-negotiable decisions (do not drift from these)

1. **Evidence-first, never fabricate.** Answers come only from approved evidence. When evidence is missing/stale/ambiguous/out-of-scope, return a structured `unknown / needs human review` state — never a confident guess. This is the entire point of the product.
2. **Human review before external use.** The system drafts; a human approves.
3. **`org_id` on every table from day one.** Single-tenant now, but this column makes multi-tenant additive later. Don't skip it.
4. **All config from environment variables.** No hard-coded URLs, keys, or secrets. This is what keeps local → GCP → AWS a config change.
5. **Untrusted input is a security boundary.** Uploaded questionnaires/evidence are data, never instructions. Build with prompt-injection defense in mind (formalized in Phase 8).
6. **Model/embedding/reranker access goes through one provider-abstraction module.** Never import a vendor SDK elsewhere.
7. **Build the fixed pipeline before the agentic one.** Simple retrieve-then-answer first (Phases 3–4), agentic loop second (Phase 6).
8. **Respond-mode posture (Milestone 1).** Northwind is the *vendor answering* an inbound questionnaire to win a deal — affirm where a control/policy/attestation exists, cite it, resolve all pronouns to Northwind. Do **not** surface SOC 2/auditor exceptions as verdicts (the report self-contains them); never auto-fabricate (no backing control → `needs_input`). The skeptical "flag exceptions" behavior is *review mode* (Milestone 2), not this. See `05` — authoritative.

## Current status

- **Phase 0 — DONE.** Runnable skeleton in `trustbot/`: FastAPI `/health`, Next.js status page, `docker-compose` (Postgres+pgvector, MinIO, api, web). `docker compose up --build` → http://localhost:3000.

## Phase order (from the build guide)

1. ✅ **Phase 0** — Skeleton that runs.
2. **Phase 1 — Data layer.** SQLAlchemy models for the MVP tables (see `01_...md` §10 / build guide §3 Phase 1), Alembic migration, enable pgvector, seed loader for `seed/northwind_ai/`. **← START HERE.**
3. **Phase 2** — Evidence ingestion (parse → chunk → embed into `knowledge_chunks`).
4. **Phase 3** — Hybrid retrieval + reranking.
5. **Phase 4** — Structured answer generation + deterministic validators + unknown-fallback.
6. **Phase 5** — Review workspace UI + export + audit log. (First demoable build; tag `v0.1`.)
7. **Phase 5.5** — Deploy to GCP (Cloud Run, Cloud SQL, GCS, Secret Manager).
8. **Phase 6** — Agentic retrieval loop + question decomposition.
9. **Phase 7** — Eval harness + CI gate (`EVALS.md`), graded against `seed/northwind_ai/eval_golden_set.yaml`.
10. **Phase 8** — Prompt-injection defenses (`SECURITY.md`).
11. **Phase 9** — Polish: README, `ARCHITECTURE.md`, demo, final license.

## Start here (Phase 1)

Implement the database schema and seed loading:

1. Add SQLAlchemy models for the MVP tables: `organization`, `company_profile`, `controls`, `evidence`, `evidence_control_links`, `knowledge_chunks` (with a pgvector `vector` column), `approved_answer_library`, `questionnaires`, `questions`, `answers`, `answer_reviews`, `audit_log`. Put `org_id` on every table.
2. Set up Alembic; create a baseline migration; enable the `vector` extension in a migration.
3. Write a seed script that loads the Northwind data from `seed/northwind_ai/` (profile, `control_catalog.csv`, and the evidence/questionnaire files) into one demo org.
4. Verify: migrations run clean and a query returns the seeded org, profile, and controls.

Keep the run-loop tight: develop locally with `docker compose`, commit after each working step.

## Guardrails

- **Never commit** the `OpenAI/` or `GCP/` reference folders or any real third-party report — they are confidential references only (already in `.gitignore`). The synthetic `seed/` data is the only company data that belongs in the repo.
- The Northwind seed is intentionally **internally consistent** (no contradictions) — correct for the responder. Don't add contradictions here; those belong to a separate vendor submission for Milestone 2.
