# TrustBot — Claim/Attestation Answer Model (Revisiting Option C)

> **Status: FINALIZED design** (decisions agreed; phased migration, no big-bang rewrite). This revisits and partially **reverses** the Option C rejection in `05_TrustBot_Respond_Mode_Design.md` §3. We adopt Option C's **core** — a structured claim → attestation model as the answer's backbone — and explicitly **drop** the part still judged unnecessary (the SOC 2 disclosure register). Migration is incremental and eval-gated.
> **Companion documents:** `05_TrustBot_Respond_Mode_Design.md` (respond posture, outcome taxonomy, the original A/B/C decision), `06_TrustBot_Adaptive_Retrieval_Loop.md`, `02_TrustBot_Vendor_Review_Component.md` (review mode inherits this model), `CLAUDE.md`.

---

## 1. Why We're Revisiting

`05` §3 chose Option B (two postures over a shared engine) and rejected Option C (rebuild the answer model around claim→attestation chains) as over-built, because most answers are "retrieve a control → affirm → cite," which retrieval + citations already express informally.

That was correct **for the goal and information at the time** (a portfolio slice shipped fast, a domain that looked simple). Two inputs have since changed:

1. **A recurring class of bug.** The system infers *what an answer means* by pattern-matching the prose, which is inherently **polarity-blind**. It has now mis-fired three times: the outcome classifier on NW-004 and NW-070 (a qualified "no" read as a "yes"), and the certification validator flagging *"certification claimed without supporting evidence: ['fedramp']"* on a correct, well-grounded **negative** ("No, not FedRAMP authorized"). These are not edge cases; they are the structural failure mode of free-prose-plus-keyword-validation.
2. **The audience and stakes.** This is moving from "portfolio piece" toward something security/compliance partners will see and potentially use. That raises the bar from "looks good" to **correct, robust, and defensible** — which is exactly Option C's strength. A structured claim→attestation model is also the *right product shape* for a GRC audience: they think in "assertion → backing evidence → status," and a banner that contradicts the evidence panel beside it actively erodes their trust in the tool.

There is also a **consolidation** argument: the build has been incrementally reinventing C anyway. Multi-part decomposition yields per-part answers with their own outcomes and citations; approved-answer reuse carries provenance; the cert fix adds a structured cert field. These are all *claims with attestations* in disguise. A claim model unifies them instead of accreting special cases.

---

## 2. Decision

**Adopt Option C's core — make a structured claim → attestation representation the backbone of every answer — and validate the structure, not the prose.** With two qualifications:

- **Drop the disclosure register.** SOC 2 exceptions remain self-contained in the report's management response (`05` Domain Rule 2). The valuable part of C is the claim/attestation structure, not the register.
- **Evolve, do not big-bang rewrite.** M1 is working, audited, and eval-gated. The migration is phased (§7), each phase guarded by the eval gate so faithfulness and overclaiming never regress.

---

## 3. The Model: Claims as the Single Source of Truth

Today the model emits prose, and the prose is then (a) classified into an outcome and (b) keyword-scanned by validators — two re-derivations of meaning that can disagree with each other and with the cited evidence. That divergence *is* the bug class.

Under this model the generator emits a **structured set of claims**, and everything else is **derived from** them:

- The **prose answer** is a rendering of the claims (and is consistency-checked against them).
- The **outcome** (`attested` / `qualified` / `negative` / `needs_input`) is **computed from** the claims, not separately classified.
- The **validators** operate on the claims, not the prose.

One representation, no divergence. The model — which understands polarity perfectly — *declares* what it asserts; deterministic code enforces the rules on those declarations.

### 3.1 Claim shape (sketch)

```
Claim:
  subject            # "FedRAMP", "encryption at rest", "background checks"
  claim_type         # certification | control | practice | attestation
  status             # affirmed | qualified | denied | unknown
  basis[]            # resolvable refs owned by the org: policy / control /
                     #   attestation / approved_answer  (server-side resolved)
  confidence         # composite (relevance + authority + agreement + coverage)
  customer_shareable
```

### 3.2 Outcome derived from claims

- All claims `affirmed` and each has a resolvable basis → **`attested`**.
- Any `qualified` (a vendor-stated scope, not an auditor exception) → **`qualified`**.
- A truthful `denied` with no unsupported affirmations → **`negative`**.
- Any `affirmed`/`qualified` claim **lacking** a resolvable basis → **`needs_input`** (anti-fabrication, unchanged in spirit).
- Nothing answerable → **`needs_input`**.

Deriving the outcome from declared claim status is what retires the classifier polarity bugs (NW-004/NW-070): a `denied` cert can never be read as a "yes," because the status *is* the source of truth.

### 3.3 Validators on structure

- **Anti-fabrication / acceptable basis:** every `affirmed`/`qualified` claim must cite ≥1 resolvable owned basis (policy / control / attestation / **prior approved answer**, per `05` §5.1), else → `needs_input`.
- **Certification overclaim:** a `certification` claim with `status: affirmed` must have an attestation basis; a `status: denied` certification is **never** flagged. *(This is the FedRAMP fix, expressed structurally — and it handles mixed answers like "SOC 2 certified, not FedRAMP" per-claim.)*
- **No internal-only content / no system-prompt leakage:** evaluated per claim and on the rendered prose.
- **Open-finding-needs-a-date:** unchanged (uses the remediation/findings register from `05` §9).
- **Prose ↔ claims consistency:** the rendered prose must not assert something the claims deny (or vice versa); divergence → flag for human review. This keeps the model from declaring one thing structurally and writing another.

---

## 4. What Stays, What's Dropped

**Stays (unchanged):** hybrid retrieval + reranking, the adaptive loop and multi-part decomposition, the review workspace + audit log, the findings/remediation register (`05` §9), the eval gate, org-scoping/tenancy, the injection defense, human approval before external use.

**Dropped:** the SOC 2 disclosure register from the original Option C (unnecessary — the report self-contains its management response).

**Consolidated under claims (later phases):** multi-part sub-answers, approved-answer-reuse provenance, the cert field — each becomes claims rather than a separate mechanism.

---

## 5. Guardrails (so this doesn't over-correct)

- **Lightweight for the simple case.** A one-line affirmative ("Yes, encrypted at rest, per [policy]") is a single claim; the common case must not become a ceremony.
- **Deterministic enforcement.** Validators run on the structured claims with code, not model judgment; the model only *declares* claims.
- **Two backstops against a mis-declared claim:** the prose↔claims consistency check, and human review before anything is external.
- **The eval gate guards the migration.** Every phase must hold or improve faithfulness, overclaiming, and the injection adversarial suite — no regression ships.

---

## 6. Why This Suits the (GRC) Audience

For security/compliance reviewers, a per-claim "assertion → exact backing evidence → status" view is the native mental model and is auditable and defensible by construction. The review workspace can surface claims explicitly (each with its citation and status), which reads as rigor. It also eliminates the trust-eroding contradiction (a "claim without evidence" banner next to evidence that says the opposite).

---

## 7. Phased Migration Plan (each phase eval-gated, via PRs on protected `main`)

**Phase 1 — Certifications as structured claims (the immediate FedRAMP fix; increment one).**
Introduce the `Claim` structure scoped to **certifications**. The generator emits certification claims with `status` + `basis`. The certification validator reads the structure (flag only `affirmed` without an attestation; never a `denied`). Derive the outcome for certification questions from claim status. Add negative-polarity tests to the hard-fail tier (a denial must not trip the validator; a genuine overclaim still must; a mixed answer flags only the unsupported affirmation). **Result: the FedRAMP banner bug is fixed structurally, not patched.**

**Phase 2 — General claims + outcome derivation.**
Extend claims to control/practice assertions. Migrate the acceptable-basis gate and the leakage check to read claims. Derive the *general* outcome from claims, retiring the separate prose classifier path that produced NW-004/NW-070.

**Phase 3 — Consistency + UI.**
Add the prose↔claims consistency validator. Surface per-claim citations and status in the review workspace (the GRC-legible view).

**Phase 4 — Consolidation.**
Express multi-part sub-answers and approved-answer-reuse provenance as claims, removing the parallel mechanisms.

---

## 8. Security & Validation Notes (CLAUDE.md in force)

- Claim `basis` refs are **server-side resolved** to real, org-owned records (same discipline as document/approved-answer refs) — the model names a ref, the system resolves it; an unresolvable or cross-org ref is fabrication and rejected.
- All claim queries are `org_id`-scoped; default deny.
- Validators remain deterministic; the model declares, code enforces; human approves before external use.
- The eval gate (including the injection adversarial suite) gates every phase; no faithfulness/overclaim/leakage regression ships.

---

## 9. Relationship to `05`

This supersedes the Option C rejection in `05` §3 **on the narrow point of the claim/attestation backbone**, for the reasons in §1 (new evidence + changed audience). The rest of `05` stands: the respond posture, the outcome taxonomy (now *derived* from claims rather than separately classified), the document-access model, the approved-answer-reuse rules, and the findings register. The disclosure-register half of Option C remains rejected.
