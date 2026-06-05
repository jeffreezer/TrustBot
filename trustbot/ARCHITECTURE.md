# Architecture & design decisions

A running log of notable, non-obvious decisions — the *why* behind the code, so
future changes don't relitigate settled tradeoffs. Newest sections may be added
as later phases land. Scope to date: **Milestone 1, Phases 1–2 (data layer +
evidence ingestion).**

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

### Character-based chunking (not token-based)
`chunk_text()` uses fixed-size character windows with overlap (`CHUNK_SIZE` /
`CHUNK_OVERLAP`). Char windows keep chunking **tokenizer-free**, so tests and CI need
no model. It's deterministic — same text + params → same chunks — which is what makes
re-ingestion idempotent and unit-testable. Token-aware chunking can replace this later
behind the same function signature if retrieval quality needs it.

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

- **Reranker** access through the same provider abstraction (Phase 3).
- The **fixed retrieve-then-answer pipeline before** any agentic loop.
- Model-output validation (cited evidence exists and is org-owned; no certification
  claimed without support; no internal-only content in customer-facing answers).
- Authn/z and org-scoping on API routes (this endpoint set is a single-tenant demo).
