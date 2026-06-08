# TrustBot — Respond-Mode Design & Course Correction (Milestone 1)

> **Status: FINALIZED design** (decisions agreed; no code yet). Course correction for the Milestone 1 Questionnaire Responder, which drifted into *reviewer* voice (surfacing auditor exceptions as answer verdicts; reading questionnaire pronouns from the buyer's side). This document defines the **respond-mode** posture the responder should have, the document-access security model, the authentication sequencing, and the contained set of changes to get there. It **supersedes** the answer-generation guidance in `04` where they conflict.
> **Companion documents:** `01_TrustBot_MVP_Portfolio_Plan.md` (Milestone 1), `02_TrustBot_Vendor_Review_Component.md` (Milestone 2 / review mode), `03_TrustBot_Full_Vision_Roadmap.md`, `04_TrustBot_MVP_Build_Guide.md`, and `../CLAUDE.md` (security + core principles, in force).

---

## 1. The Problem We Caught

Milestone 1's job: **Northwind AI is the vendor**, answering an *inbound* security questionnaire from a prospective customer to support a sale. The correct posture is a vendor's trust/security team putting its best **honest, affirmative** foot forward — "Yes, access is provisioned least-privilege and reviewed quarterly, per our Access Control Policy; this control is covered by our SOC 2 Type II."

What the build actually does is behave like a skeptical **assessor reading the vendor's evidence for problems** — it leads with "Has Exception," surfaces the SOC 2's auditor exceptions as the headline answer, and (because it reads "your/their" from the buyer's side) returns `unknown` on questions that merely ask about Northwind's own practices.

That assessor posture is not wasted work — it is the **head start on Milestone 2** (third-party vendor review). The fix is therefore a **reframe, not a teardown**: introduce the respond posture for Milestone 1, and relabel the existing reviewer behavior as Milestone 2's review posture.

---

## 2. The Two Postures (One Platform)

| | **Respond mode** (Milestone 1) | **Review mode** (Milestone 2) |
|---|---|---|
| Whose answers | Ours (Northwind) | The vendor's |
| Goal | Draft affirmative, evidence-cited answers to win deals | Assess a vendor's answers for risk |
| Findings/exceptions | Do **not** surface as verdicts; the report self-contains them; remediation status attached only when a document is provided | Surfaced as risk findings — the whole point |
| Default stance | Affirm where a control exists | Question until substantiated |
| Core rule | "Don't fabricate claims about *us*" | "Don't fabricate conclusions about *them*" |

**Shared, posture-agnostic (unchanged):** ingestion, evidence store, hybrid retrieval + reranking, the review workspace, async generation jobs, tenancy seam, audit log, provider abstraction.
**Forks per posture:** the generation step (system instructions, outcome taxonomy, validators) and the eval golden set.

---

## 3. Decision: Option B + a Remediation Register

Three approaches were evaluated: (A) a posture switch on the existing pipeline; (B) two first-class postures over shared infrastructure; (C) a full rebuild of the answer model around claim→attestation chains with a disclosure register.

**Chosen: Option B**, plus the single genuinely-structured element borrowed from C — a **remediation register** for findings.

Why not C: the domain reality makes C over-built. Most answers are "a control/policy/attestation exists → affirm → cite," which retrieval + citations already express. SOC 2 exceptions are **self-contained** (the report's management response handles them — Northwind adds no context), so C's exception-disclosure machinery is unnecessary. The one place real structure is needed is pentest-report provision (remediation status + closure dates), which B absorbs as a focused feature. The remediation register also doubles as Milestone 2 infrastructure (tracking a third party's findings is the identical shape).

> **Revisited (see `07_TrustBot_Claim_Attestation_Model.md`).** New evidence — a recurring polarity-blind bug class (the FedRAMP "certification claimed without evidence" false-positive on a correct negative) and a higher GRC-audience bar — reverses this on the **narrow point** of the claim/attestation backbone: TrustBot now adopts Option C's *core* (structured claim → attestation, validated on the structure not the prose), phased and eval-gated, while still **dropping** C's disclosure register. Phase 1 of that migration scopes claims to certifications (the structural FedRAMP fix). The rest of `05` stands.

---

## 4. Domain Rules This Design Encodes

The real-world rules that drive the mechanics below:

1. **Affirm if a control/policy/procedure exists** — even if the SOC 2 or pentest has findings. Findings do not downgrade an affirmation.
2. **SOC 2 exceptions need no Northwind context.** The management response is baked into the report. The drafter generates **zero** exception commentary; it affirms the control and references the report.
3. **Pentest questions take two forms:** "Do you conduct annual penetration testing?" (a plain affirmative + cadence) versus "Provide your most recent pentest report" (a document-provision answer).
4. **Providing a pentest report obligates remediation transparency:** current remediation status for all findings, plus planned closure dates for any open findings.

---

## 5. Respond-Mode Outcome Taxonomy

Four outcome states describe *what kind of answer this is*. Two attributes carry the document/remediation mechanics so they don't pollute the taxonomy.

| Outcome | Meaning | Drafted? |
|---|---|---|
| `attested` | A control / policy / procedure / attestation backs an affirmative answer. Default success state. Cites backing evidence. | Yes — affirmative draft |
| `qualified` | Affirmative **with a vendor-stated scope** the vendor would itself volunteer (e.g., "CMK on Enterprise tier only"). Not an auditor exception. | Yes — affirmative draft + caveat |
| `negative` | An honest "no" the vendor would truthfully give (e.g., "Not FedRAMP authorized"). Not hidden. | Yes — drafted, flagged for reviewer attention |
| `needs_input` | No controlling control/policy/attestation found, **or** the question needs human judgment / a disclosure call / engagement-specific info the corpus can't supply. | No draft — explicit "a human must answer this" |

**Attributes (not outcomes):**
- `requires_document` + `provided_documents[]` — set for document-request questions; the answer affirms and references the providable artifact (access-controlled — see §8).
- `remediation_required` + linked finding IDs — set when a provided document carries findings; the answer renders current status + closure dates from the register (§9).

**Rules baked in:**
- **No `has_exception` state exists.** A SOC 2 exception never changes the outcome. A SOC 2-covered control answers `attested` + "addressed in our SOC 2 Type II, control CCx.x" with **no** exception commentary.
- **Findings never downgrade an affirmation.** They live in the register and surface only when a report is provided.
- **Anti-fabrication gate (the old "never fabricate," reframed):** a validator requires every `attested`/`qualified` answer to cite a **resolvable basis owned by the org** — a policy, control, attestation, **or a prior approved answer** (see §5.1). If none resolves, it **must** fall to `needs_input`. The model's own ungrounded assertion never counts. Default deny.

**Migration from the current (reviewer) states:** `supported_yes` → `attested`; `has_exception` → `attested` (exception dropped) or occasionally `qualified` (only if the caveat is a vendor *scope*, not an auditor finding); `supported_no` → `negative` or `needs_input`; `unknown` → `needs_input`.

### 5.1 Approved-answer reuse (a valid basis without a document)

Many real questionnaire answers are narrative attestations an analyst wrote and **approved** with no underlying document (e.g., "Describe your approach to X"). These approved answers are reusable by the system — this is core principle #7 ("approved-answer reuse is a candidate, not a bypass"), now made explicit for the document-less case.

- **A resolved prior approved answer is a valid basis.** The acceptable-basis set for an `attested`/`qualified` answer is: policy, control, attestation, **or a resolved prior approved answer** owned by the org. With none of these → `needs_input`. The model's own ungrounded assertion never counts.
- **Resolve server-side, never model-named.** An approved-answer citation must resolve to a real approved-answer record owned by the org (same discipline as document refs). A model-claimed approved answer that doesn't resolve is fabrication and is rejected — this is what stops reuse from becoming a laundering loophole.
- **Always cite the prior approval.** The draft must show "Based on prior approved answer [ref]" so the reviewer sees exactly what they are confirming and the determination stays traceable.
- **Outcome + review.** An approved-answer basis yields `attested`/`qualified` (**not** `needs_input` — we have a vetted candidate, not "nothing"), but with `needs_human_review = true`, reason "reused prior approval — confirm still accurate." Never auto-emitted; always human-confirmed.
- **Lower authority tier + freshness.** Treat an approved-answer-only basis as lower authority than a document-backed one (the existing composite-confidence source-authority factor), and carry a freshness signal (last-approved/validated date); a stale reuse flags harder.
- **Provenance chain.** Record each answer's basis (this answer ← approved answer X) so the grounding chain stays traceable and an ungrounded claim cannot bootstrap into apparent "evidence" over successive reuse.

Schema: add an approved-answer reference to the basis/citation set plus a provenance/freshness record on reuse. The workspace "Save to library" action already creates approved-answer candidates; extend it to capture analyst-authored, document-less answers with their provenance.

---

## 6. Perspective Resolution

Respond-mode binds first/second/third-person references — "you / your / their / the organization / the vendor" — to **Northwind, the respondent**. Inbound questionnaires are templated and often phrase questions awkwardly ("what access to *their* endpoints do employees get"); "their" means Northwind's own employees/devices. This single rule eliminates the wrong-side `needs_input` results the current build produces. The generation system prompt states the respondent identity explicitly and instructs the model to resolve perspective accordingly — while still treating questionnaire text as **data, never instructions** (CLAUDE.md).

---

## 7. Question-Type Classification

Before drafting, classify the question:
- **Attestation** ("Do you do X?", "Describe your approach to X") → affirmative + cite the control/policy/attestation. No document, no findings.
- **Document-request** ("Provide your SOC 2 / pentest report / ISO cert") → affirm + set `requires_document`; reference the artifact (access-controlled); if the artifact carries findings, set `remediation_required` and render the remediation block.

---

## 8. Document Access, Provision & Security (Layer 1 + Audit)

Sensitive documents (SOC 2, pentest) must **not** be delivered as a bearer link — a signed/shareable URL grants access to *whoever holds it*, so an intercepted or forwarded link is effectively the document itself. The access decision must be based on **proven identity, not possession of a link**. Documents are therefore served only through an authenticated, org-scoped, audited endpoint.

### 8.1 Milestone 1 mechanism — what we build now

| Piece | Implementation |
|---|---|
| **The guarded endpoint** | New product route `GET /documents/{document_id}/download`. Order of checks: (1) resolve caller's org via the existing `get_current_org` seam; (2) look up the document **by id, filtered by `org_id`** — cross-org → `404` (default deny, no existence leak); (3) confirm it's shareable (`customer_shareable` and referenced by an approved answer); (4) **stream the bytes** via `StreamingResponse`. |
| **Document-id, never a path** | The client passes a `document_id`; the **server** resolves the real storage key from the record. Never accept a client-supplied file path (CLAUDE.md file-handling rule). |
| **Storage adapter** | Add `get_object_stream(key)` to the existing MinIO/GCS/S3 adapter. The file only ever flows *through* the checked endpoint — no raw signed URL is handed to the client. (If a signed URL is ever needed for large files, mint it server-side, single-use, seconds-long, behind the same checks.) |
| **Audit** | Reuse the existing `audit_log` table. New action `document_downloaded`: actor/org, `document_id`, timestamp, IP. Metadata only — never file contents or secrets, consistent with existing audit discipline. |
| **UI + export point at the door** | The answer's `provided_documents[]` render as links to `/documents/{id}/download` — never to storage. Export references documents via that endpoint (or a "available in the workspace" note); the exported file contains **no bearer link**. |

**What this buys (Milestone 1):** intercepting a link gains nothing (the door checks the person, not a ticket); every access is attributable to a person + time; access is **instantly revocable** (flip `customer_shareable` / remove the grant → next request denied), unlike a pre-issued signed link that lives until expiry.

**Honest limit:** no technical control stops an *authorized* recipient from re-sharing a file they can already see. That is addressed (deter + trace, not absolutely prevent) by watermarking / view-only / NDA in the trust-center milestone (§8.3).

### 8.2 The "authenticated" caveat today

The app currently has no end-user login; it runs on the `get_current_org` seam as a single tenant, and the consumer in Milestone 1 is Northwind's own reviewer previewing a document before providing it. The point now is to build the **correct shape** — every document access through one org-scoped, audited, server-checked endpoint — so that stronger identity (§11) plugs into the same seam without touching the route or its queries.

### 8.3 Deferred to the trust-center milestone (NOT built now)

Stronger controls, layered on **in front of** the same endpoint when external-recipient delivery becomes the actual feature:
- **Recipient identity:** magic-link / passwordless email auth (authenticate the requester, not the link), or recipient accounts. Pulls in **email infrastructure** (provider + SPF/DKIM/DMARC deliverability) — real overhead, low $ cost, abstracted behind a provider interface with a dev console fallback.
- **Blast-radius reduction:** single-use tokens, very short expiries, stream-through.
- **Deter + trace re-sharing:** per-recipient watermarking, view-only/no-download rendering, anomaly alerts.
- **Process gate:** access request + NDA acceptance, approved by a Northwind reviewer, before any grant; a per-recipient **grants table**.

### 8.4 Cost note

Signed-URL signing itself is free (a local cryptographic operation). The only costs are ordinary object storage — at-rest (~pennies for small PDFs), egress on download (~$0.09/GB; negligible at these sizes), and request ops. **MinIO locally is free.** This feature has no always-on cost component (unlike Cloud SQL).

### 8.5 Document selection (which artifact to attach)

How the attached artifact(s) for a document-request question are chosen:

- **Named artifact** (the question names SOC 2 / ISO / PCI / pentest): **kind-based auto-attach.** Select org-scoped, `customer_shareable` evidence whose `document_kind` matches the requested artifact(s), attaching all that apply. Never substitute a whitepaper for an attestation; a requested artifact absent from the corpus is flagged for human review, never substituted.
- **Generic request** (no specific artifact named — e.g. "share relevant documentation," "attach your relevant policy"): **always surface an analyst picker** — providing a document is a human disclosure decision, so the system does not silently auto-attach. Present the org's `customer_shareable` evidence documents, relevance-ranked to the question (via the existing retrieval), each labeled by `document_kind` + title. **Pre-select the cited governing document** as the recommended choice (one-click confirm in the common case), but the analyst can deselect it and choose other shareable artifacts; if the answer has no cited governing document, the picker opens with nothing pre-selected. Nothing attaches until the analyst confirms; selection resolves **server-side** (a real shareable, org-owned record) and writes a `document.attach` audit entry.

---

## 9. Remediation Register Data Model

A `findings` table — org-scoped, shareability-aware, reusable by Milestone 2 (tracking a third party's findings is identical).

| Field | Notes |
|---|---|
| `id` | |
| `org_id` | Tenancy — enforced on every query. Default deny. |
| `source_document_id` + `source_type` | `pentest` \| `soc2_exception` \| `internal_audit` \| `vuln_scan` … |
| `external_ref` | The finding's ID as labeled in the report (e.g., "IDOR-01"). |
| `title` / description | |
| `severity` | **Stored verbatim as the source report rates it** (`High`, `P1`, `CVSS 8.1`, …). We do not impose our own scale. Optional derived `severity_rank` for UI sorting only. |
| `status` | `open` \| `in_progress` \| `remediated` \| `risk_accepted` \| `closed`. (`risk_accepted` included — real programs accept some risk with sign-off.) |
| `identified_date` | |
| `target_remediation_date` | Planned closure; nullable. |
| `remediated_date` | Actual closure; nullable. |
| `remediation_summary` | Short, **customer-shareable** text of what's being/been done. |
| `owner` | Internal accountable party (internal-only). |
| `customer_shareable` + `confidentiality` | Customer-facing render shows shareable fields only, via the existing shareability gate. |
| `created_at` / `updated_at` | |

**Customer-facing render** (when a report is provided): `external_ref`, `severity`, `status`, `target/closure date`, shareable `remediation_summary`. Internal fields (`owner`, internal notes) are filtered out.

**Validator (encodes Domain Rule 4):** a provided pentest with an `open`/`in_progress` finding that has **no** `target_remediation_date` **cannot auto-draft** → route to `needs_input`. You cannot send a report with an open finding and no plan, so the system refuses and asks a human.

---

## 10. Worked Examples

- **"Do you conduct annual penetration testing?"** → `attested`; cites the testing cadence in the security policy. No findings, no document.
- **"Provide your most recent penetration test report."** → `attested`, `requires_document` + `remediation_required`; references the report (access-controlled) and renders the remediation block (open IDOR finding, in-progress, target date). If that finding lacked a target date → `needs_input`.
- **"Do you enforce access control and timely termination?"** (currently mis-firing as Has Exception) → `attested`; cites the Access Control / Offboarding policy and the SOC 2; the SOC 2 termination-timeliness exception is **not surfaced** — the report's management response owns it.
- **"Are you HIPAA certified?"** → `negative`; drafted truthfully ("HIPAA offers no certification; we are not a Business Associate for this offering"), flagged for reviewer attention rather than hidden.

---

## 11. Authentication & Authorization Sequencing

Two distinct "end users" need auth at different times: **internal users** (Northwind reviewers) and **external recipients** (the customer pulling shared documents). Adoption is **trigger-based**, and each trigger maps to a depth of auth. The whole sequence is deferrable cheaply because everything already runs through the `get_current_org` seam — adding identity is "wire it into the seam," not a rewrite.

| Trigger | What it adds | When |
|---|---|---|
| **Now (M1 local demo)** | Nothing — keep the seam, no login. The consumer is the single operator. | Current |
| **"Reachable by someone other than me"** | **IAP** in front of Cloud Run — a Google-verified identity at the edge with ~zero auth code; read the asserted identity into the seam. This is the first real authenticated identity. | The deferred **cloud real-model demo** step (bundled with putting the LLM key in Secret Manager + `GENERATION_PROVIDER=anthropic`). |
| **"More than one human operates it / audit must say *who* / want to show RBAC"** | Lightweight app login (OIDC/OAuth or session auth) + basic **roles** (reviewer / approver / admin). Identity = who you are; authorization = what you may do. | **Hardening / productionization phase** (alongside build-guide Phases 8–9), after the agentic loop + eval gate that showcase the marketable skills. |
| **"More than one organization on one instance"** + **external document delivery** | Full multi-tenant auth (identity *drives* org, never client-supplied) + external-recipient **magic-link** (§8.3). | **Trust-center milestone.** |

---

## 12. Surface Area of Change

**Changes (contained):**
- Generation system instructions (respondent identity + perspective resolution; affirm-and-cite; SOC 2 exception suppression; question-type handling).
- Outcome taxonomy (§5) and answer-schema attributes (`requires_document`, `provided_documents[]`, `remediation_required`).
- Validators (anti-fabrication gate reframed; open-finding-needs-a-date gate).
- New `findings` table + remediation render.
- New `GET /documents/{id}/download` endpoint + `get_object_stream` adapter method + `document_downloaded` audit action; UI/export point at the endpoint (§8).
- Eval golden set re-authored for respond-mode (§13).
- Seed addition (§13).

**Unchanged (shared platform):** ingestion, evidence store, hybrid retrieval + reranking, review workspace, async generation jobs, tenancy seam, audit log, provider abstraction.

---

## 13. Seed & Eval Implications

- **Seed:** add structured `findings` rows for the existing pentest — the open High IDOR finding (`status: in_progress`, an `identified_date`, a future `target_remediation_date`, a shareable summary) plus its closed findings for realism. Without this, the document-request demo has nothing real to render.
- **Evals:** re-author the golden set to pin respond-mode behavior — affirm-and-cite, SOC 2 exception suppression on covered controls, the remediation-status render, the open-finding-needs-a-date refusal, perspective resolution, and **approved-answer reuse** (a question answerable only from an approved-answer-library entry → `attested` + a "prior approved answer" citation + needs-review, never `needs_input`). The current traps reward *flagging* (reviewer posture) and will fight this fix if left in place. Keep a separate review-mode golden set parked for Milestone 2.

---

## 14. Security Review Notes (CLAUDE.md in force)

- **Tenancy:** `org_id` on the `findings` table and every query/route touching it (incl. the download endpoint). Cross-org → `404`. Never trust a client-supplied org id.
- **Document access:** identity-based, not bearer-link; document-id resolved to a storage key server-side (no path injection); served via the org-scoped endpoint; every access written to the audit log; instantly revocable.
- **Shareability:** customer-facing remediation render and document access pass through the existing `customer_shareable` gate; internal-only fields and non-shareable documents never leave.
- **Untrusted content (Phase 8 — prompt-injection hardening):** questionnaire rows and ingested documents remain **data, not instructions** — perspective resolution and affirm-and-cite must not let questionnaire text override system instructions. Untrusted text reaches the model strictly as fenced grounding (never system-instruction space), is screened at the boundary (instruction-override / role / system / tool / exfiltration patterns, with zero-width and HTML-comment de-obfuscation), and — in **respond mode** — is handled by **flag-and-neutralize**: the injected directive is redacted out of the model-facing grounding (it was already inert as data), the answer is still produced from approved evidence (or `needs_input` if honest), and the item is flagged for human review with the offending snippet (metadata-only). Nothing is blocked. (Review mode, M2, uses **quarantine** — a flagged document is excluded from the retrievable KB until an explicit human release; both behaviors are built behind a per-mode policy.) See `SECURITY.md` + `ARCHITECTURE.md` for the four-layer model.
- **Output validation:** the anti-fabrication gate (cite a resolvable owned basis — policy, control, attestation, or a **server-side-resolved** prior approved answer, §5.1 — or fall to `needs_input`) and the open-finding-needs-a-date gate run before persist; reused approved answers are **always** flagged for human review with their provenance recorded; unsupported answers route to human review. A human approves before anything is external.

---

## 15. Suggested Build Sequence (no code until approved)

1. Add the `findings` table + seed rows (data layer first — walk before run).
2. Add the respond-mode outcome taxonomy + answer-schema attributes.
3. Fork the generation step: respondent identity + perspective, affirm-and-cite, SOC 2 suppression, question-type classification.
4. Validators: anti-fabrication (reframed) + open-finding-needs-a-date.
5. Document access: `GET /documents/{id}/download` (org-scoped, streamed, audited) + adapter `get_object_stream`; point UI/export at it; drop any bearer-link path.
6. Re-author the respond-mode eval golden set; keep the reviewer set parked for Milestone 2.
7. Verify end-to-end on the 59-question questionnaire: affirmative drafts, no surfaced SOC 2 exceptions, correct perspective, pentest-provision renders remediation status, document access is identity-gated + audited.

**Deferred (not this build):** recipient magic-link + email infra, per-recipient grants, watermarking/view-only (trust center); IAP identity (cloud real-model step); app login + RBAC (hardening phase); multi-tenant auth (trust center). See §8.3 and §11.
