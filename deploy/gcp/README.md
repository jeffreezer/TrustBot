# Deploying TrustBot to GCP (Cloud Run + Cloud SQL + GCS + Secret Manager)

One script, `deploy.sh`, stands up the whole stack. It is **parameterized** (every value
is an env-overridable variable) and **idempotent** (each step guards on existence, so a
re-run after a failure is safe).

## Prerequisites

- `gcloud` installed and authenticated (`gcloud auth login`), with billing enabled.
- These APIs enabled (the script also enables them idempotently): `run`, `sqladmin`,
  `artifactregistry`, `secretmanager`, `storage`, `cloudbuild`, `iam`.
- Secret Manager secret(s) created (values never read/printed/committed by the script):
  - `trustbot-db-password` — the Postgres app-user password (used for the Cloud SQL user
    and injected into the services via `--set-secrets`). **Required for every deploy.**
  - `trustbot-llm-key` — your model API key. **Only** needed for a real-model provider
    (`GENERATION_PROVIDER=anthropic` or `=api`). The default `fake` demo never references it
    — the script neither grants access to it nor injects it — so you don't create it at all
    for the public demo.

## Run

```bash
PROJECT_ID=your-project ./deploy/gcp/deploy.sh
```

`PROJECT_ID` is required and is **never** hardcoded or committed — it is read from the
environment. Region defaults to `us-central1`.

### What it deploys by default — the public, no-LLM demo

The defaults deploy a **public, clickable** demo running the deterministic **fake**
generator (`GENERATION_PROVIDER=fake`), so there is **no API key in front of an open
endpoint** — no LLM exposure, no per-request model cost. Both services are
`--allow-unauthenticated` and capped at `--max-instances=2`.

The script: creates an Artifact Registry repo → a Cloud SQL instance + database + app
user → a GCS bucket → **three least-privilege service accounts** (runtime / job / build,
see below) → builds & pushes the API image (model baked in; seed corpus staged into the
image) → deploys the API (Cloud SQL attached, `db-password` secret wired, `APP_ENV=production`)
→ runs the **migrate + seed Job once** → builds & deploys the web image with
`NEXT_PUBLIC_API_URL` set to the API's URL → tightens the API's CORS to the web origin. It
prints both URLs at the end.

`APP_ENV=production` means the **product** routes (upload / generate / review / export)
work while the **debug** routes (`/debug/summary`, `/retrieve`, `/answer`) return `404`.

### A future real-model, locked-down instance

`deploy.sh` is parameterized for it (not deployed by the demo defaults):

```bash
PROJECT_ID=your-project \
GENERATION_PROVIDER=anthropic \
GENERATION_MODEL=claude-sonnet-4-6 \
ALLOW_UNAUTH=false \
./deploy/gcp/deploy.sh
```

`GENERATION_PROVIDER=anthropic` calls the native Claude Messages API with tool-use; the
key comes from the `trustbot-llm-key` secret. (Use `=api` + `MODEL_BASE_URL` instead for
any OpenAI-compatible endpoint.)

This wires `trustbot-llm-key` into the API and deploys **locked down** (no public access —
put IAP in front). Don't expose a real model on a public URL.

### Least-privilege IAM — every grant, per identity

Three distinct service accounts, each holding **only** what it needs, so a compromise of one
cannot act as another. Keyless throughout — no static keys; each identity authenticates as
its own ADC. The complete grant list (least privilege is documented, not assumed):

**`trustbot-run` — API runtime SA** (the public Cloud Run service)

| Role | Scope |
|---|---|
| `roles/cloudsql.client` | project (the role has no resource scope) — opens the Cloud SQL socket |
| `roles/secretmanager.secretAccessor` | the **`trustbot-db-password`** secret only |
| `roles/secretmanager.secretAccessor` | the **`trustbot-llm-key`** secret only — **and only when `GENERATION_PROVIDER != fake`** (the fake demo never gets the key) |
| `roles/storage.objectUser` | the **one** bucket `gs://<project>-trustbot-evidence` only — read/write objects (no bucket admin, no object-ACL admin) |

**`trustbot-job` — migrate/seed Job SA** (one-shot, not internet-facing)

| Role | Scope |
|---|---|
| `roles/cloudsql.client` | project |
| `roles/secretmanager.secretAccessor` | the **`trustbot-db-password`** secret only — **never** the model key (the Job always runs `fake`) |
| `roles/storage.objectUser` | the one bucket only |

**`trustbot-build` — Cloud Build SA** (build-time only; builds run as this SA via `--service-account`)

| Role | Scope |
|---|---|
| `roles/cloudbuild.builds.builder` | project — the standard build role (push to Artifact Registry, write build logs, read the regional source/log bucket). **No runtime data access**: no DB, no secrets, no evidence bucket |
| `roles/iam.serviceAccountUser` *(on this SA, granted to the deployer)* | so the deploying principal can `actAs` the build SA (Owners already have this) |

**Not granted anywhere:** no `roles/editor`, no `roles/owner`, no project-wide wildcards, no
`roles/storage.admin`/`objectAdmin`, and no reliance on the broad **Compute Engine default
SA** (builds use the dedicated `trustbot-build` SA instead). v4 signed download URLs will
additionally need `roles/iam.serviceAccountTokenCreator` on `trustbot-run` — that's Phase D;
the fake demo issues no download links, so it is intentionally left ungranted.

Audit the live grants any time:

```bash
# Project-level roles held by the TrustBot SAs (expect only cloudsql.client /
# cloudbuild.builds.builder — never editor/owner):
gcloud projects get-iam-policy "$PROJECT_ID" --flatten='bindings[].members' \
  --filter='bindings.members:trustbot-' --format='table(bindings.members, bindings.role)'
# Per-secret accessors (expect trustbot-run + trustbot-job on db-password; only trustbot-run
# on llm-key, and only for a real-model deploy):
gcloud secrets get-iam-policy trustbot-db-password --format='table(bindings.role, bindings.members)'
# Bucket object access (expect objectUser for trustbot-run + trustbot-job; nothing else):
gcloud storage buckets get-iam-policy "gs://${PROJECT_ID}-trustbot-evidence" \
  --format='table(bindings.role, bindings.members)'
```

## Cost

Everything except Cloud SQL **scales to zero**: Cloud Run (API + web) and the one-shot Job
cost only while running; Artifact Registry and GCS are a few cents of storage.

**Cloud SQL (`db-f1-micro`) is the one standing cost (~$8/mo if left running).** Stop it
when idle and start it before a demo:

```bash
gcloud sql instances patch trustbot-db --activation-policy=NEVER    # stop (no compute charge)
gcloud sql instances patch trustbot-db --activation-policy=ALWAYS   # start
```

## Teardown (delete everything to stop charges)

```bash
REGION=us-central1
gcloud run services delete trustbot-api  --region=$REGION -q
gcloud run services delete trustbot-web  --region=$REGION -q
gcloud run jobs     delete trustbot-migrate-seed --region=$REGION -q
gcloud sql instances delete trustbot-db -q
gcloud storage rm -r gs://${PROJECT_ID}-trustbot-evidence
gcloud artifacts repositories delete trustbot --location=$REGION -q
gcloud iam service-accounts delete trustbot-run@${PROJECT_ID}.iam.gserviceaccount.com -q
gcloud iam service-accounts delete trustbot-job@${PROJECT_ID}.iam.gserviceaccount.com -q
gcloud iam service-accounts delete trustbot-build@${PROJECT_ID}.iam.gserviceaccount.com -q
```

(The two Secret Manager secrets are left in place — you created them; delete them
yourself if you want them gone.)
