# TrustBot

> Evidence-backed AI security questionnaire responder. **Phase 3 — hybrid retrieval** is in place on top of Phase 1 (data layer) and Phase 2 (ingestion): a question is answered by fusing pgvector cosine similarity with Postgres full-text search, then reranking the candidates with a CPU cross-encoder — all behind the same provider abstraction, with org/shareability metadata filters applied on every query. Answer generation and the review UI come in later phases (see `../04_TrustBot_MVP_Build_Guide.md`).

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

On start the API container **applies migrations and seeds the demo company automatically** (idempotent — re-runs just skip). Seeding now also **parses, chunks, and embeds** the full corpus — the company profile, every evidence file, the policy library, the control implementation statements, and the approved-answer library — into `knowledge_chunks`, each tagged with a distinct `source_type`. Markdown is chunked **structure-aware** (split on section headings, with each document's front-matter routed to metadata rather than embedded), falling back to overlapping character windows for oversized sections or heading-less sources. Then open **http://localhost:3000** for the health page, or hit the API directly.

> **Port 3000 already in use?** The web UI's host port is configurable. Set `WEB_PORT` (e.g. `WEB_PORT=3001` in your `.env`) and open that port instead — the container-internal port stays 3000, so nothing else changes.

Services:

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 (or `WEB_PORT`) |
| API health | http://localhost:8000/health |
| Seed summary | http://localhost:8000/debug/summary |
| Retrieve (POST) | http://localhost:8000/retrieve |
| MinIO console | http://localhost:9001 (user `trustbot` / pass `trustbot123`) |
| Postgres | localhost:5432 (user/pass/db `trustbot`) |

> The `trustbot` / `trustbot123` credentials are **local-only throwaway demo values**, not real secrets. In `docker-compose.yml` they're written as `${VAR:-default}`, so the demo runs with zero setup but any value can be overridden from the environment. Real deployments inject secrets via the environment / a secret manager (GCP Secret Manager, AWS Secrets Manager); outside `local`/`dev`/`test` the API **refuses to start** if `DATABASE_URL` (or S3 credentials) are missing — fail-closed, no hard-coded fallback.

`GET /debug/summary` returns the seeded org and row counts — a quick way to confirm the data layer is populated:

```json
{ "seeded": true, "org": {"name": "Northwind AI, Inc.", "slug": "northwind-ai"},
  "counts": {"controls": 30, "evidence": 5, "policies": 16, "evidence_control_links": 72,
             "approved_answers": 369, "knowledge_chunks": 532} }
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

## Repository layout

```
trustbot/
├── docker-compose.yml      # postgres+pgvector, minio, api, web
├── .env.example            # all config keys (env-var driven)
├── backend/                # FastAPI service
│   ├── alembic.ini
│   ├── entrypoint.sh       # migrate → seed → serve
│   └── app/
│       ├── main.py         # /health, /debug/summary
│       ├── config.py       # env-var settings
│       ├── seed.py         # loads + ingests the Northwind demo company
│       ├── db/             # engine, models, alembic migrations
│       ├── storage/        # storage adapter: local + S3 (MinIO/GCS/S3)
│       ├── providers/      # model abstraction: embeddings + reranker (local | hash | api/none)
│       ├── ingestion/      # parse → chunk → embed → knowledge_chunks
│       └── retrieval/      # hybrid search (vector + keyword) → fuse → rerank
└── frontend/               # Next.js app (health status page)
```

Synthetic demo/test data (the fictional "Northwind AI" company) lives in `../seed/` and is mounted read-only into the API container, then loaded by `app/seed.py`.

## Roadmap

This is Milestone 1. Phase 1 (data layer), Phase 2 (ingestion: parse → chunk → embed), and Phase 3 (hybrid retrieval + reranking) are in place. Subsequent phases add answer generation (fixed pipeline, then agentic), the review workspace, evals, and security hardening. See `../04_TrustBot_MVP_Build_Guide.md`.

## License

MIT — see [LICENSE](LICENSE).
