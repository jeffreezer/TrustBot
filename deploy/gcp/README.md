# Deploying TrustBot to GCP (Cloud Run + Cloud SQL + GCS + Secret Manager)

One script, `deploy.sh`, stands up the whole stack. It is **parameterized** (every value
is an env-overridable variable) and **idempotent** (each step guards on existence, so a
re-run after a failure is safe).

## Prerequisites

- `gcloud` installed and authenticated (`gcloud auth login`), with billing enabled.
- These APIs enabled (the script also enables them idempotently): `run`, `sqladmin`,
  `artifactregistry`, `secretmanager`, `storage`, `cloudbuild`, `iam`.
- Two Secret Manager secrets created (values never read/printed/committed by the script):
  - `trustbot-db-password` — the Postgres app-user password (used for the Cloud SQL user
    and injected into the services via `--set-secrets`).
  - `trustbot-llm-key` — your model API key. **Only** wired in for a real-model provider
    (`GENERATION_PROVIDER=anthropic` or `=api`); the default `fake` demo never receives it.

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
user → a GCS bucket → a least-privilege runtime service account → builds & pushes the API
image (model baked in; seed corpus staged into the image) → deploys the API (Cloud SQL
attached, `db-password` secret wired, `APP_ENV=production`) → runs the **migrate + seed
Job once** → builds & deploys the web image with `NEXT_PUBLIC_API_URL` set to the API's
URL → tightens the API's CORS to the web origin. It prints both URLs at the end.

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

### Least-privilege service account

The runtime SA gets exactly: **Secret Accessor** on the two secrets (resource-level),
**Cloud SQL Client** (project-level, required to open the socket), and **Storage Object
Admin on the one bucket only**. Keyless auth throughout — no static keys. (v4 signed
download URLs additionally need `roles/iam.serviceAccountTokenCreator` on the SA; the demo
doesn't issue download links, so that role is left ungranted.)

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
```

(The two Secret Manager secrets are left in place — you created them; delete them
yourself if you want them gone.)
