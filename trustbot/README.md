# TrustBot

> Evidence-backed AI security questionnaire responder. **Phase 5 — the review workspace** is in place on top of Phases 1–4: upload a questionnaire → the system drafts an evidence-cited answer for each question (or an explicit **unknown / needs-human-review** state) → a human reviews, edits, approves or rejects in a three-pane workspace → export with approval status. Drafting retrieves against pgvector + Postgres FTS (fused and reranked), grades each answer with a **composite** confidence (relevance + authority + agreement + coverage, *not* the rerank score), and runs deterministic validators before persisting. Nothing is auto-emitted — a human approves before anything is external. This is the first demoable build (`v0.1`).

TrustBot drafts answers to security questionnaires using only a company's verified, approved evidence — and flags anything it can't support for human review, instead of guessing. Open source (MIT) and self-hostable: your security data never has to leave your infrastructure.

## Stack

- **Backend:** Python + FastAPI
- **Database:** PostgreSQL + pgvector (same engine local, GCP Cloud SQL, or AWS RDS)
- **Object storage:** S3-compatible (MinIO locally; GCS or S3 in cloud)
- **Frontend:** Next.js (React)
- All configuration via environment variables, so local → GCP → AWS is a config change, not a rewrite.

## Run it

```bash
cp .env.example .env        # optional for docker; compose sets container values
docker compose up --build
```

> **First `--build` is heavier.** The API image bakes in the local **BGE-M3** embedding model (~1–2 GB) at build time, so the running container needs no model download and no network at runtime. Embeddings run on **CPU** — expected and fine at demo scale. To skip the model entirely (e.g. fast CI), set `EMBEDDING_PROVIDER=hash` for a deterministic, dependency-free fake, or `EMBEDDING_PROVIDER=api` to point at an OpenAI-compatible embedding server (`MODEL_BASE_URL` / `MODEL_API_KEY`).

On start the API container **applies migrations and seeds the demo company automatically** (idempotent — re-runs just skip). Seeding now also **parses, chunks, and embeds** the full corpus — the company profile, every evidence file, the policy library, the control implementation statements, and the approved-answer library — into `knowledge_chunks`, each tagged with a distinct `source_type`. Markdown is chunked **structure-aware** (split on section headings, with each document's front-matter routed to metadata rather than embedded), falling back to overlapping character windows for oversized sections or heading-less sources. The seed also loads a **sample inbound questionnaire** (18 questions) ready to answer. Then open **http://localhost:3000** for the review workspace, or hit the API directly.

> **Port 3000 already in use?** The web UI's host port is configurable. Set `WEB_PORT` (e.g. `WEB_PORT=3001` in your `.env`) and open that port instead — the container-internal port stays 3000, so nothing else changes.

Services:

| Service | URL |
|---|---|
| Review workspace (UI) | http://localhost:3000 (or `WEB_PORT`) |
| API health | http://localhost:8000/health |
| Seed summary | http://localhost:8000/debug/summary |
| Questionnaires (REST) | http://localhost:8000/questionnaires |
| Retrieve (POST, debug) | http://localhost:8000/retrieve |
| Answer (POST, debug) | http://localhost:8000/answer |
| MinIO console | http://localhost:9001 (user `trustbot` / pass `trustbot123`) |
| Postgres | localhost:5432 (user/pass/db `trustbot`) |

> The `trustbot` / `trustbot123` credentials are **local-only throwaway demo values**, not real secrets. In `docker-compose.yml` they're written as `${VAR:-default}`, so the demo runs with zero setup but any value can be overridden from the environment. Real deployments inject secrets via the environment / a secret manager (GCP Secret Manager, AWS Secrets Manager); outside `local`/`dev`/`test` the API **refuses to start** if `DATABASE_URL` (or S3 credentials) are missing — fail-closed, no hard-coded fallback.

`GET /debug/summary` returns the seeded org and row counts — a quick way to confirm the data layer is populated:

```json
{ "seeded": true, "org": {"name": "Northwind AI, Inc.", "slug": "northwind-ai"},
  "counts": {"controls": 30, "evidence": 5, "policies": 16, "evidence_control_links": 72,
             "approved_answers": 369, "knowledge_chunks": 532,
             "questionnaires": 1, "questions": 18} }
```

`knowledge_chunks` is populated by the Phase 2 ingestion pipeline (parse → chunk → embed) across five `source_type`s — `company_profile`, `evidence`, `policy` (governed policy documents), `control` (implementation statements), and `approved_answer` (the prior approved Q&A, retrievable reuse candidates). The exact count depends on chunking: Markdown is split on section headings (front-matter routed to metadata, not embedded), with an overlapping-window fallback (`CHUNK_SIZE` / `CHUNK_OVERLAP`) for oversized sections and heading-less sources. With the defaults the seed yields ~532 chunks.

`GET /debug/summary` is an introspection endpoint, so it is **gated to non-production environments** (`APP_ENV` in `local`/`dev`/`test`). In any other environment it returns `404` — fail-closed, so it can't leak from a production deploy.

### Hybrid retrieval (`POST /retrieve`)

Phase 3 adds hybrid retrieval: a question is embedded and searched two ways — **pgvector cosine** similarity and **Postgres full-text** — the two ranked lists are merged with **Reciprocal Rank Fusion**, and a CPU **cross-encoder reranker** (`ms-marco-MiniLM`) re-sorts the candidates so the genuinely best evidence ends up on top. Every query is **org-scoped** and accepts metadata filters (`source_types`, `confidentiality`, `customer_shareable`) — the same shareability gate Phase 4 will use to keep internal-only material out of customer-facing answers.

```bash
curl -s localhost:8000/retrieve -H 'content-type: application/json' \
  -d '{"question": "Do you encrypt data at rest?", "top_k": 3}' | jq
```

Like `/debug/summary`, `/retrieve` returns chunk **text**, so it is **gated to non-production** (`404` otherwise). It's a tuning/demo endpoint; the request body is bounded and validated at the boundary. Set `RERANKER_PROVIDER=hash` (deterministic lexical fake) or `none` (skip the cross-encoder) to run retrieval without the reranker model.

### Answer generation (`POST /answer`)

Phase 4 drafts a structured, evidence-cited answer from the retrieved grounding — or an explicit `unknown / needs_human_review` state when the evidence is missing, insufficient, low-confidence, or conflicting. It **never fabricates**: the draft is grounded only in retrieved, customer-shareable evidence, deterministic validators run before persist (cited evidence must exist and be org-scoped; no certification claimed without an attestation record; no internal-only content in a customer-facing answer), and the draft is **persisted but never auto-emitted** — a human approves in Phase 5.

```bash
curl -s localhost:8000/answer -H 'content-type: application/json' \
  -d '{"question": "What are your data classification levels?"}' | jq
```

**Confidence is a composite, not the rerank score.** The rerank logit measures relevance only; the answer's `confidence` blends relevance + **source authority** + **cross-source agreement** + **question coverage**, so a fact stated verbatim in an authoritative policy scores `high` even when its rerank logit is modest. The response includes `confidence_factors` showing the breakdown.

The demo runs the deterministic, grounding-only **fake** generator (`GENERATION_PROVIDER=fake`, set in compose) so the stack needs no external model and CI stays offline. For real drafting choose a backend: **`anthropic`** (native Claude Messages API with **tool-use** to force the answer schema — set `MODEL_API_KEY`; default model `claude-sonnet-4-6`), or **`api`** for any OpenAI-compatible server (`MODEL_BASE_URL` / `MODEL_API_KEY` / `GENERATION_MODEL` — OpenAI, vLLM, Ollama's `/v1`). All three sit behind the one provider abstraction; the answers layer validates the output identically regardless. Like `/retrieve`, `/answer` returns answer text and is **gated to non-production**.

The golden set can be run through this path (safety gates: unknown-fallback, no overclaim, the data-classification answer lists the four tiers and cites the policy):

```bash
docker compose exec -T api python -m evals.run_evals
```

### Review workspace (Phase 5)

The workspace at **http://localhost:3000** is the product surface. The demo flow, end to end:

1. **Upload** a questionnaire (CSV/Excel; one question per row) — or use the sample the seed already loaded (`seed/northwind_ai/questionnaires/Inbound_Security_Questionnaire.csv`, 18 questions spanning supported answers, honest negatives, SOC 2 exceptions, and unknown-fallback traps). The file is stored via the storage adapter with a recorded hash, parsed into questions, and screened for injection-like content — never executed.
2. **Generate drafts** — one Phase-4 answer per question (composite confidence, full-top-k synthesis, unknown-fallback, validators).
3. **Review** in three panes: the question list with a status per item · the selected question with its editable draft, outcome, confidence, and the `needs_human_review` reason shown prominently · the supporting evidence / cited sources on the right. Each action — **approve / edit / reject / request-evidence / save-to-library** — transitions the answer's status and writes an `audit_log` entry (labels only, never answer text). "Save to library" creates an approved-answer *candidate* (re-validated on future reuse, never an authoritative bypass).
4. **Export** to CSV/Excel — every row carries `review_status` + `needs_human_review`, so nothing reads as final that a human didn't approve.

These review endpoints are the product (not gated like the debug ones); they are **org-scoped** via a single tenancy seam (`get_current_org`) so real auth slots in later without touching the queries. The upload accepts the file as the raw request body (filename via query) — no multipart dependency. PDF intake is rejected at the boundary for now (CSV/Excel only).

## Repository layout

```
trustbot/
├── docker-compose.yml      # postgres+pgvector, minio, api, web
├── .env.example            # all config keys (env-var driven)
├── backend/                # FastAPI service
│   ├── alembic.ini
│   ├── entrypoint.sh       # migrate → seed → serve
│   └── app/
│       ├── main.py         # health, debug, + mounts the review router
│       ├── review_routes.py # Phase 5: upload / generate / review / export
│       ├── deps.py         # get_current_org — the single tenancy seam
│       ├── config.py       # env-var settings
│       ├── seed.py         # loads + ingests the Northwind demo company
│       ├── db/             # engine, models, alembic migrations
│       ├── storage/        # storage adapter: local + S3 (MinIO/GCS/S3)
│       ├── providers/      # model abstraction: embeddings + reranker + generation
│       ├── ingestion/      # parse → chunk → embed → knowledge_chunks
│       ├── retrieval/      # hybrid search (vector + keyword) → fuse → rerank
│       ├── answers/        # draft → composite confidence → validate → GeneratedAnswer
│       └── questionnaires/ # intake parsing + review service (status, audit, export)
├── evals/                  # golden-set eval harness for the generation path
└── frontend/               # Next.js review workspace (list/upload + three-pane review)
```

Synthetic demo/test data (the fictional "Northwind AI" company) lives in `../seed/` and is mounted read-only into the API container, then loaded by `app/seed.py`.

## Deploy to GCP

`../deploy/gcp/deploy.sh` stands up the whole stack on **Cloud Run + Cloud SQL + GCS + Secret Manager** — the same images you run locally, only env changes:

```bash
PROJECT_ID=your-project ./deploy/gcp/deploy.sh
```

It's parameterized and idempotent. By default it deploys a **public, clickable demo on the deterministic `fake` generator** (no API key in front of an open endpoint), capped at `--max-instances 2`. `APP_ENV=production` keeps the product routes working while the debug routes 404. Object storage uses a keyless **GCS** backend (ADC — no static keys); Cloud SQL connects over a unix socket with the password injected from Secret Manager by name; a one-shot Cloud Run **Job** migrates + seeds once (never on cold start). See [`../deploy/gcp/README.md`](../deploy/gcp/README.md) for prerequisites, the **cost note** (Cloud SQL is the one standing cost — stop it when idle), and **teardown** commands.

## Roadmap

This is Milestone 1. Phase 1 (data layer), Phase 2 (ingestion: parse → chunk → embed), Phase 3 (hybrid retrieval + reranking), Phase 4 (answer generation: the fixed retrieve-then-answer pipeline with composite confidence, structured output, and deterministic validators), **Phase 5 (review workspace + export + audit — the first demoable build, `v0.1`)**, and **Phase 5.5 (deploy to GCP — Cloud Run + Cloud SQL + GCS + Secret Manager)** are in place. Subsequent phases add the agentic retrieval loop (Phase 6), the full eval gate (Phase 7), and security hardening. See `../04_TrustBot_MVP_Build_Guide.md`.

## License

MIT — see [LICENSE](LICENSE).
