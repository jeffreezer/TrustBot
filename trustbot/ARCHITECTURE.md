# Architecture & design decisions

A running log of notable, non-obvious decisions — the *why* behind the code, so
future changes don't relitigate settled tradeoffs. Newest sections may be added
as later phases land. Scope to date: **Milestone 1, Phases 1–4 (data layer +
evidence ingestion + hybrid retrieval + answer generation).**

## Guiding constraints

These come from `CLAUDE.md` and the build guide and shape every decision below:

- **Evidence-first, never fabricate.** Missing/stale/ambiguous evidence yields a
  structured *needs-human-review* state, never a confident guess.
- **Security is not a phase.** When convenience and security conflict, security wins.
- **`org_id` on every table from day one.** Single-tenant now; multi-tenant additive.
- **All config from environment variables.** The same image runs local → GCP → AWS.
- **Untrusted input is data, never instructions.**

---

## Data layer

### UUID primary keys (not auto-increment integers)
Every table's `id` is a `uuid4`. Sequential integer keys are enumerable (leak row
counts, invite IDOR probing) and collide across tenants when data is merged or
migrated. UUIDs are non-guessable, safe to expose, and let rows be generated
client- or service-side without a round trip. Cost — slightly larger keys/indexes —
is irrelevant at this scale.

### `org_id` foreign key on every table, indexed, `ON DELETE CASCADE`
A shared `_org_fk()` helper puts a `org_id → organization.id` FK on every domain
table, indexed (tenancy filters hit it on every query) and cascading (deleting an
org cleanly removes its data). It is the single tenancy boundary the whole product
enforces; making it structural now means the multi-tenant roadmap is *additive*,
not a rewrite. `audit_log.org_id` is nullable so system-level events can be recorded.

### Timestamp mixin with DB-side defaults
`created_at` / `updated_at` use `server_default=now()` (and `onupdate`) so timestamps
are authoritative at the database, not dependent on app clocks or every code path
remembering to set them.

### Vector column nullable until Phase 2
`knowledge_chunk.embedding` is `pgvector` `Vector(1024)` (BGE-M3 dimensionality) and
**nullable** — chunks can exist before embeddings are computed. The pgvector
extension is enabled in its own migration (`0001`) ahead of the baseline schema.

### `metadata` column mapped to attribute `meta`
SQLAlchemy's declarative base reserves the class attribute `metadata`. The
`knowledge_chunk` JSONB column is therefore declared as
`meta: Mapped[dict] = mapped_column("metadata", JSONB, ...)` — Python-side `meta`,
DB-side `metadata`, so the schema reads naturally without shadowing the ORM.

### Approved answers are reusable *candidates*, not an authoritative bypass
The approved-answer library is seeded and will be retrievable, but a reused answer
must be **re-validated against current evidence before being emitted**. It shortcuts
drafting, never the evidence-first guarantee — stale or now-unsupported answers must
not slip through just because they were once approved.

---

## Migrations

- **DB URL is never stored in `alembic.ini`.** `env.py` reads it from
  `settings.database_url` (i.e. the environment). Connection strings are secrets;
  they don't belong in a checked-in config file.
- **Two revisions:** `0001` enables the pgvector extension; `0002` is the baseline
  schema. `compare_type=True` so future autogenerate catches column-type drift.
- Migrations + seed run on container start via `entrypoint.sh` (migrate → seed →
  serve), both idempotent, with a short retry loop to absorb DB/MinIO startup races.

---

## Object storage

### One adapter, `STORAGE_BACKEND`-selected
A `StorageAdapter` interface has `local` (filesystem) and `s3` (MinIO/GCS/S3)
implementations chosen by `STORAGE_BACKEND`. Application code never imports boto3
or touches a filesystem path directly — local → cloud is a config change.

### Bucket provisioning goes *through the adapter*, not hard-coded to MinIO
`ensure_bucket()` is a no-op on the base/local adapter and a real head-or-create on
S3. The seed calls the adapter to provision storage; nothing special-cases MinIO.
This keeps the demo one-command while staying portable to GCS/S3. *(Direct
instruction: "do it through the storage adapter, not hard-coded to MinIO.")*

### Security properties baked into the adapter
- **Path-traversal defense:** `safe_object_key()` rejects empty keys, `..` segments,
  absolute paths, and null bytes, and normalizes separators — a hostile object key
  can't escape its prefix and become an arbitrary file write. The local adapter adds
  a defense-in-depth `is_relative_to(base)` check. Pinned by `tests/test_storage_keys.py`.
- **Private by default:** S3 objects are written with no public ACL; downloads are
  served via short-lived **presigned URLs**, never public buckets.
- **Integrity:** every stored file records a **sha256** hash.
- **Tenant-namespaced keys:** `org/{org_id}/evidence/{evidence_id}/{filename}`, with
  filenames sanitized.
- **Encryption at rest:** optional `S3_SSE` (e.g. `AES256`/`aws:kms`), empty by
  default so the local MinIO demo isn't broken; turned on in cloud.

---

## Seed data

- **Synthetic Northwind company only.** Real third-party reports and the confidential
  `OpenAI/` / `GCP/` reference folders never enter the repo.
- **Treated strictly as data, never instructions** — the first instance of the
  untrusted-input boundary the whole product depends on. Filenames are sanitized
  before storage.
- **Sibling of `trustbot/`, mounted read-only** (`../seed:/seed:ro`) so the app can
  never mutate the source data; path is configurable via `SEED_DATA_DIR`.
- **Idempotent:** re-running skips already-seeded rows. The `audit_log` entry records
  **counts only** — never secrets or document contents.

---

## Evidence ingestion (Phase 2)

### One provider abstraction for embeddings — the only vendor-specific code
`app/providers/` is the *single* place model/SDK-specific code lives (CLAUDE.md).
Callers do `from app.providers import get_embedding_provider` and depend only on the
`EmbeddingProvider` contract; nothing else imports sentence-transformers, torch, or
an HTTP client. Three implementations, selected by `EMBEDDING_PROVIDER`:
- **`local`** (default) — BGE-M3 on CPU via sentence-transformers.
- **`hash`** — deterministic, dependency-free fake for tests / offline CI. Same text
  always yields the same unit vector, so ingestion is testable without a download.
- **`api`** — OpenAI-compatible `/v1/embeddings` (stdlib HTTP, no extra SDK), for a
  hosted or self-hosted embedding server.
`_validate()` enforces that every provider returns `EMBEDDING_DIM`-wide vectors, so a
misconfigured model fails loudly instead of corrupting the `Vector(1024)` column.

### Local model baked into the image at build time
The Dockerfile installs **CPU-only torch** (from PyTorch's CPU index, to avoid the
multi-GB CUDA build) and pre-downloads BGE-M3 during `docker compose up --build`. The
running container then has **no network dependency and no first-request download** —
heavier build, predictable runtime. CPU inference is acceptable at demo scale.

### Structure-aware chunking, with a character-window floor
`chunk_document()` (in `ingestion/structure.py`) is the primary path: for Markdown it
splits on section headings so each section becomes one topically coherent chunk
(the document's H1 title is prepended as lightweight context). Two fallbacks make it
**never worse** than the old window chunker: a section larger than `CHUNK_SIZE` is
window-chunked, and a document with no usable heading structure (tables, the
questionnaire-derived answers, future PDFs) is window-chunked whole. The underlying
`chunk_text()` floor is still fixed-size character windows with overlap (`CHUNK_SIZE` /
`CHUNK_OVERLAP`) — tokenizer-free, so tests and CI need no model, and deterministic, so
re-ingestion stays idempotent and unit-testable.

This was a real retrieval fix, not a refactor: a fixed 1,200-char window over a policy
was dominated by ~430 chars of leading boilerplate (title block, disclaimer, the `>`
metadata blockquote), so the chunk holding the four data-classification tiers reranked
*dead last*. `extract_front_matter()` now routes that leading blockquote — the
disclaimer and `**Key:** value` lines (Owner, Version, Classification, Related controls)
— into the chunk's `meta['front_matter']` instead of embedding it as body text, while
keeping the `#` title and `##` headings (useful retrieval signal). It keys on Markdown
structure, never on specific wording, so real customer policies with the same header
shape work the same way. Document text is parsed and sliced only — **data, never
instructions** — and the parsing regexes are segment-bounded (no catastrophic
backtracking).

### Ingestion is idempotent and tenant-scoped
`ingest_document()` validates size at the boundary (`MAX_INGEST_BYTES`), requires an
`org_id`, then **deletes any prior chunks for the exact (org_id, source_type,
source_id) before inserting** — re-running the seed never duplicates or strands rows.
The pure chunk+embed core (`build_chunk_rows`) is DB-free so it's unit-tested with the
hash provider; the DB round-trip is verified end-to-end via `/debug/summary`.

### Content is data, never instructions
`parse_document()` only decodes and normalizes text; it never interprets, executes, or
follows links inside a document. Phase 2 handles text/markdown only and **rejects
unsupported binary types at this boundary** rather than mishandling them. Each chunk's
`meta` carries `confidentiality` / `customer_shareable` copied from the source so Phase
3 retrieval and Phase 4 answer validation can filter without re-joining evidence.

### One knowledge base over five source types
The corpus is embedded into a single `knowledge_chunks` table, each chunk tagged with a
distinct `source_type` so Phase 3 can retrieve across — and weight — them:
- **`company_profile`** — canonical company facts (internal).
- **`evidence`** — uploaded attestation documents, carrying their own
  confidentiality / shareable flags (e.g. SOC 2 = confidential-but-shareable, the
  whitepaper = public).
- **`policy`** — governed policy documents. Stored as `evidence` rows
  (`evidence_type='policy'`) so they are linkable to controls via
  `evidence_control_links`, but their chunks are tagged `source_type='policy'` to stay
  distinct in retrieval. Confidentiality / shareability is read from each file's
  `Classification:` header, never a hardcoded table.
- **`control`** — control implementation statements. Embedded as `code + title +
  statement`, tagged **internal, not customer-shareable**: a control statement *informs*
  a drafted answer, but the drafted answer is what goes external, never the raw statement.
- **`approved_answer`** — the prior approved Q&A library, embedded as the `Q: … / A: …`
  pair so a new, similar question matches on the question side and the answer is right
  there for reuse. Tagged shareable (these were real external responses) but treated as a
  retrievable **candidate, re-validated against current evidence before emission** — never
  an authoritative bypass (see the data-layer note above). Going through structured
  `ingest_text()` (not the document parser) keeps these rows off the file path while
  sharing the same chunk → embed → idempotent-upsert core.

---

## Retrieval (Phase 3)

### Hybrid: vector + keyword, fused by rank — not by score
Cosine distance (pgvector) and full-text rank (`ts_rank_cd`) live on different,
incomparable scales, so the two ranked lists are merged with **Reciprocal Rank
Fusion** (`1/(k+rank)`, `k=60`) rather than by blending raw scores. RRF is
parameter-light, robust to scale differences, and lets each retriever contribute its
ordering without one swamping the other. The fusion step (`retrieval/fusion.py`) is
pure and DB-free, so it's unit-tested directly. Vector search alone misses exact-term
matches (control codes, acronyms); keyword search alone misses paraphrases — together
they cover both.

### Keyword search is parameterized Postgres FTS — no injection surface
`keyword_search` builds `to_tsvector('english', chunk_text) @@ plainto_tsquery('english', :q)`
with the question passed as a **bound parameter**, never string-concatenated, so a
hostile question can't inject SQL (CLAUDE.md). A GIN index on the *same*
`to_tsvector('english', chunk_text)` expression (migration `0003`) keeps it fast; the
`'english'` config must match on both sides or the planner ignores the index.

### Exact vector search (no ANN index) at demo scale
Cosine search runs without an IVFFlat/HNSW index — at a few hundred chunks an exact
scan is fast and avoids the recall/tuning tradeoffs of an approximate index. An ANN
index is a drop-in later (larger corpus) behind the same query.

### Reranker is the only new vendor code — same provider abstraction
`ms-marco-MiniLM` (CPU cross-encoder) re-scores the fused candidates so the genuinely
best evidence rises to the top. Like embeddings, it lives **only** in `app/providers/`
behind a `RerankProvider` contract, selected by `RERANKER_PROVIDER`:
- **`local`** (default) — the cross-encoder, baked into the image at build time.
- **`hash`** — a deterministic *lexical-overlap* fake. Unlike a pure hash it yields
  meaningful ordering (most query-term overlap wins), so retrieval ordering is
  unit-testable offline without the model.
- **`none`** — a passthrough that returns equal scores; the stable sort then preserves
  the fused order exactly (isolate/disable the reranker).
The pipeline scores once and sorts itself (ties broken by fusion score) so the debug
endpoint can surface both `fusion_score` and `rerank_score` for tuning.

### Filters are the tenancy + shareability gate, applied on every query
`RetrievalFilters` carries a **required** `org_id` plus optional `source_types`,
`confidentiality`, and `customer_shareable`. A shared `_base_stmt` applies them to
*both* retrievers, so org-scoping (CLAUDE.md: "on every query") can't be forgotten on
one path. `customer_shareable=True` is the exact filter Phase 4 will use to keep
internal-only material out of customer-facing answers — the security guarantee is
enforced at retrieval, not bolted on afterward.

### A fixed pipeline, before any agentic loop
`retrieve()` is a deliberately fixed embed → search → fuse → rerank → top-k pipeline
(CLAUDE.md: "fixed retrieve-then-answer pipeline before the agentic loop"). It returns
`RetrievedChunk`s for Phase 4 to draft and validate against. `POST /retrieve` exposes
it for tuning/demos and is **gated to non-production** (it returns chunk text) with a
bounded, validated request body.

---

## Answer generation (Phase 4)

The fixed retrieve-then-answer pipeline (`app/answers/`): `retrieve → draft → resolve
citations → composite confidence → deterministic validators → GeneratedAnswer`. Still
fixed (no agentic loop / decomposition — that's Phase 6); the model drafts, a human
approves (Phase 5). Every branch **fails closed**.

### rerank = relevance only; confidence = composite of relevance + authority + agreement + coverage
The cross-encoder rerank score measures query↔chunk *relevance* and nothing else — it's
an uncalibrated, source-blind logit, so it must **never** be the answer's confidence or
the human-review trigger on its own. `answers/confidence.py` computes a composite of
four signals instead:
- **relevance** — a gentle logistic squash of the cited chunks' rerank score (a soft
  term, never a gate);
- **authority** — weight by `source_type` (policy / SOC 2 evidence / control / approved
  answer are authoritative; the company profile less so);
- **agreement** — how many *independent* source documents corroborate the claim;
- **coverage** — do the cited chunks actually contain the salient terms of the question.

Authority + coverage deliberately dominate the weights, so an answer **stated verbatim in
an authoritative policy resolves to HIGH even when the rerank logit is modest or
negative** — the exact failure the Phase 3 analysis surfaced. Only a `high` band clears
without a review flag; anything lower routes to a human.

### Synthesize over the full top-k, not the #1 chunk
The generator is grounded on the whole top-k, and (when sources are redundant) prefers
citing the **authoritative** one. In Phase 3 a vague approved answer outranked the chunk
that actually listed the data-classification tiers; a #1-only approach would have
produced the weaker answer.

### Generation behind the provider abstraction; instructions ≠ data
A `GenerationProvider` (the only place an LLM is touched) is selected by
`GENERATION_PROVIDER`: **`api`** (OpenAI-compatible `/v1/chat/completions` via
`MODEL_BASE_URL`/`MODEL_API_KEY`, default) or **`fake`** (a deterministic, grounding-only
stand-in for tests/CI/demo that *cannot fabricate* — it returns `unknown` when grounding
is insufficient). Trusted instructions go in the **system** channel; the question and
retrieved evidence go in the **user** channel, fenced and labeled as data. Retrieved text
is **data, never instructions**: `detect_injection` screens it and routes injection-like
content to review rather than acting on it.

### Deterministic validators, run before persist/return (fail closed)
The model is never trusted to self-police. `answers/validate.py` (pure, DB-free, so it's
unit-tested without a database) checks: required fields present and confidence in range;
**every cited evidence id exists and is org-scoped** (a hallucinated or out-of-scope
citation fails); **no certification asserted without a supporting attestation record**
(catches FedRAMP / SOC 1 overclaims); and **no internal-only / non-customer-shareable
evidence in a customer-facing answer** (the same Phase 3 gate — and retrieval already
filters to `customer_shareable=True`, so it's defense in depth). Any failure → routed to
human review with the reason, never silently dropped.

### Unknown-fallback and approved-answer re-validation
Missing, insufficient, low-composite-confidence, or conflicting evidence, a malformed
draft, or a failed validator all yield the structured `unknown / needs_human_review`
state — never a guess (principle 1). A draft cited **only** to a prior approved answer is
treated as a reuse *candidate*, not a bypass (principle 7): it is flagged for review as
"not corroborated by current evidence," so an approved answer is re-validated, never
echoed verbatim.

### Persistence and the eval harness
`generate → validate → persist`: the answer is written to `answers` (with an
`audit_log` entry carrying labels/counts only — never answer text) against a
materialized ad-hoc `Question`, keeping referential integrity without a schema change.
`POST /answer` exposes it, **gated to non-production** like `/retrieve`. `evals/run_evals.py`
runs the golden set through this path; its *gates* are the deterministic safety
guarantees (unknown-fallback for FedRAMP/HIPAA/SOC 1, no overclaim, the NW-005
data-classification answer lists the four tiers and cites the policy), while outcome
accuracy is reported as a generator-dependent metric.

---

## API surface & configuration

- **Introspection is fail-closed.** `GET /debug/summary` is gated to non-production
  environments (`APP_ENV` ∈ `local`/`dev`/`test`) and returns `404` otherwise, so a
  production deploy can't leak it. It is counts-only with no secrets regardless.
- **`audit_log` is append-only** and its `payload` must never contain secrets or PII.
- **Host web port is parameterized** (`WEB_PORT`, default `3000`). Hard-coding the
  port caused a collision with another local service; making it configurable is the
  12-factor-consistent fix and spares self-hosters the same clash.

---

## Deferred to later phases (explicitly not built yet)

- The **review workspace** (Phase 5): the human approve / edit / reject UI over the
  drafted answers. Generation flags `needs_human_review`; the workspace acts on it.
- The **agentic retrieval loop** (Phase 6) — a `search_knowledge_base` tool the model
  drives itself. The fixed retrieve-then-answer pipeline (above) lands first, by design.
- An **ANN vector index** (IVFFlat/HNSW) — unneeded at demo scale; exact search now.
- Authn/z and org-scoping on API routes (this endpoint set is a single-tenant demo).
