#!/usr/bin/env bash
#
# Deploy TrustBot to Google Cloud Run + Cloud SQL + GCS + Secret Manager.
#
# Parameterized and idempotent: every step guards on existence, so re-running after a
# failure is safe. PROJECT_ID is never hardcoded — it comes from the environment. The two
# Secret Manager secrets are referenced BY NAME (--set-secrets / in-process for the SQL
# user password); their values are never printed, logged, or committed (note: no `set -x`).
#
# Defaults deploy the PUBLIC, no-LLM demo: GENERATION_PROVIDER=fake on a public URL, so
# there is no API key in front of an open endpoint. Override the vars below for a future
# IAP-gated real-model instance (GENERATION_PROVIDER=api + trustbot-llm-key + ALLOW_UNAUTH=false).
#
# Usage:
#   PROJECT_ID=your-project ./deploy/gcp/deploy.sh
#
# Required APIs (enable once; the script also enables them idempotently):
#   run, sqladmin, artifactregistry, secretmanager, storage, cloudbuild, iam
set -euo pipefail

# ---- parameters (env-overridable) -------------------------------------------------
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID (never hardcoded/committed)}"
REGION="${REGION:-us-central1}"

REPO="${REPO:-trustbot}"                              # Artifact Registry repo
INSTANCE="${INSTANCE:-trustbot-db}"                   # Cloud SQL instance
DB_NAME="${DB_NAME:-trustbot}"
DB_USER="${DB_USER:-trustbot}"
BUCKET="${BUCKET:-${PROJECT_ID}-trustbot-evidence}"   # GCS bucket (globally unique)
SA_NAME="${SA_NAME:-trustbot-run}"                    # runtime service account
CLOUD_SQL_TIER="${CLOUD_SQL_TIER:-db-f1-micro}"       # smallest/cheapest demo tier
CLOUD_SQL_EDITION="${CLOUD_SQL_EDITION:-ENTERPRISE}"  # shared-core tiers need Enterprise (not Plus)

DB_PASSWORD_SECRET="${DB_PASSWORD_SECRET:-trustbot-db-password}"
LLM_KEY_SECRET="${LLM_KEY_SECRET:-trustbot-llm-key}"

API_SERVICE="${API_SERVICE:-trustbot-api}"
WEB_SERVICE="${WEB_SERVICE:-trustbot-web}"
JOB_NAME="${JOB_NAME:-trustbot-migrate-seed}"
API_MEMORY="${API_MEMORY:-8Gi}"                       # CPU model inference (BGE-M3 + reranker);
                                                      # 4Gi OOMs loading the model + embedding
API_CPU="${API_CPU:-2}"
MAX_INSTANCES="${MAX_INSTANCES:-2}"                   # low cap to bound a public demo

# Generation: this deploy uses the deterministic fake (no LLM, no key wired in). For a
# real-model instance set GENERATION_PROVIDER=anthropic (native Claude Messages API +
# tool-use; default model below) — or =api for any OpenAI-compatible endpoint via
# MODEL_BASE_URL. Either wires the model key from the trustbot-llm-key secret.
GENERATION_PROVIDER="${GENERATION_PROVIDER:-fake}"
GENERATION_MODEL="${GENERATION_MODEL:-claude-sonnet-4-6}"
MODEL_BASE_URL="${MODEL_BASE_URL:-https://api.anthropic.com/v1}"

# Access posture. PUBLIC for the clickable fake-gen demo. Set ALLOW_UNAUTH=false for a
# locked-down (IAP-gated) deployment — required if you ever switch to GENERATION_PROVIDER=api.
ALLOW_UNAUTH="${ALLOW_UNAUTH:-true}"

# ---- derived ----------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/trustbot/backend"
FRONTEND_DIR="$REPO_ROOT/trustbot/frontend"
SEED_DIR="$REPO_ROOT/seed"

INSTANCE_CONN="${PROJECT_ID}:${REGION}:${INSTANCE}"
AR_HOST="${REGION}-docker.pkg.dev"
IMAGE_API="${AR_HOST}/${PROJECT_ID}/${REPO}/api:latest"
IMAGE_WEB="${AR_HOST}/${PROJECT_ID}/${REPO}/web:latest"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

AUTH_ARGS=()
if [ "$ALLOW_UNAUTH" = "true" ]; then
  AUTH_ARGS+=(--allow-unauthenticated)
else
  AUTH_ARGS+=(--no-allow-unauthenticated)
fi

# Always restore the seed_bundle placeholder, even on failure (it is gitignored anyway).
cleanup() {
  find "$BACKEND_DIR/seed_bundle" -mindepth 1 ! -name .gitkeep -exec rm -rf {} + 2>/dev/null || true
}
trap cleanup EXIT

# Retry a command a few times — IAM bindings on a freshly created service account can fail
# briefly while the identity propagates (eventual consistency).
retry() {
  local n=0
  local max=6
  until "$@"; do
    n=$((n + 1))
    if [ "$n" -ge "$max" ]; then
      return 1
    fi
    echo "  (retry $n/$max in 10s)" >&2
    sleep 10
  done
}

echo ">>> Project=$PROJECT_ID  Region=$REGION  Generation=$GENERATION_PROVIDER  Public=$ALLOW_UNAUTH"
gcloud config set project "$PROJECT_ID" >/dev/null

# ---- 0. APIs (idempotent; you may have enabled these already) ----------------------
gcloud services enable \
  run.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com storage.googleapis.com cloudbuild.googleapis.com \
  iam.googleapis.com >/dev/null

# ---- 1. Artifact Registry ----------------------------------------------------------
if ! gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1; then
  echo ">>> Creating Artifact Registry repo $REPO"
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker --location="$REGION" --description="TrustBot images"
fi

# ---- 2. Cloud SQL (THE standing cost) ----------------------------------------------
echo ">>> Cloud SQL: $INSTANCE  tier=$CLOUD_SQL_TIER (smallest, shared-core) — ~\$8/mo if left"
echo "    running, no HA, no backups. THIS IS THE ONE STANDING COST. Stop it when idle:"
echo "    gcloud sql instances patch $INSTANCE --activation-policy=NEVER"
if ! gcloud sql instances describe "$INSTANCE" >/dev/null 2>&1; then
  gcloud sql instances create "$INSTANCE" \
    --database-version=POSTGRES_16 --edition="$CLOUD_SQL_EDITION" --tier="$CLOUD_SQL_TIER" \
    --region="$REGION" --storage-type=HDD --storage-size=10GB \
    --no-backup --availability-type=zonal
fi
if ! gcloud sql databases describe "$DB_NAME" --instance="$INSTANCE" >/dev/null 2>&1; then
  gcloud sql databases create "$DB_NAME" --instance="$INSTANCE"
fi
# Set the SQL user's password FROM the secret, in-process. The value is never printed or
# stored (no `set -x`); the same secret is injected into the services via --set-secrets.
if gcloud sql users describe "$DB_USER" --instance="$INSTANCE" >/dev/null 2>&1; then
  gcloud sql users set-password "$DB_USER" --instance="$INSTANCE" \
    --password="$(gcloud secrets versions access latest --secret="$DB_PASSWORD_SECRET")"
else
  gcloud sql users create "$DB_USER" --instance="$INSTANCE" \
    --password="$(gcloud secrets versions access latest --secret="$DB_PASSWORD_SECRET")"
fi
# Note: the pgvector extension is created by Alembic migration 0001 in the migrate-seed
# Job (the gcloud-created user is a cloudsqlsuperuser and may create allowlisted extensions).

# ---- 3. GCS bucket -----------------------------------------------------------------
if ! gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  echo ">>> Creating GCS bucket gs://$BUCKET"
  gcloud storage buckets create "gs://$BUCKET" \
    --location="$REGION" --uniform-bucket-level-access
fi

# ---- 4. Least-privilege runtime service account ------------------------------------
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  echo ">>> Creating service account $SA_EMAIL"
  gcloud iam service-accounts create "$SA_NAME" --display-name="TrustBot Cloud Run runtime"
fi
# Secret Accessor on the two secrets only (resource-level, not project-wide). Retried
# because a just-created service account can take a moment to be usable as a member.
for secret in "$DB_PASSWORD_SECRET" "$LLM_KEY_SECRET"; do
  retry gcloud secrets add-iam-policy-binding "$secret" \
    --member="serviceAccount:$SA_EMAIL" \
    --role=roles/secretmanager.secretAccessor >/dev/null
done
# Cloud SQL Client (project-level; required to open the socket).
retry gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/cloudsql.client --condition=None >/dev/null
# Storage Object Admin on the ONE bucket only.
retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectAdmin >/dev/null

# Cloud Build runs as the Compute Engine default service account; newer projects don't
# grant it the build role by default, so it can't read the build source bucket or push to
# Artifact Registry. Grant the builder role (one-time, build-time identity — separate from
# the least-privilege runtime SA above).
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
CLOUDBUILD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
retry gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$CLOUDBUILD_SA" \
  --role=roles/cloudbuild.builds.builder --condition=None >/dev/null

# ---- 5. Build + push the API image (bakes the model; stage the seed into the image) -
echo ">>> Building API image (first build downloads the model, ~10-15 min)"
cp -R "$SEED_DIR/." "$BACKEND_DIR/seed_bundle/"
gcloud builds submit "$BACKEND_DIR" --tag "$IMAGE_API" --timeout=3600
cleanup

# ---- 6. Deploy the API (Cloud SQL attached, secrets wired, no seed on cold start) ---
API_ENV="APP_ENV=production,STORAGE_BACKEND=gcs,GCS_BUCKET=${BUCKET}"
API_ENV="${API_ENV},CLOUD_SQL_INSTANCE=${INSTANCE_CONN},DB_USER=${DB_USER},DB_NAME=${DB_NAME}"
API_ENV="${API_ENV},RUN_MIGRATIONS=false,RUN_SEED=false,SERVE=true,GENERATION_PROVIDER=${GENERATION_PROVIDER}"
API_SECRETS="DB_PASSWORD=${DB_PASSWORD_SECRET}:latest"
# Real-model providers (anthropic | api) get the model + key; only the OpenAI-compatible
# 'api' path also needs a base URL. 'fake' wires no key (no LLM in front of the demo).
if [ "$GENERATION_PROVIDER" != "fake" ]; then
  API_ENV="${API_ENV},GENERATION_MODEL=${GENERATION_MODEL}"
  API_SECRETS="${API_SECRETS},MODEL_API_KEY=${LLM_KEY_SECRET}:latest"
  if [ "$GENERATION_PROVIDER" = "api" ]; then
    API_ENV="${API_ENV},MODEL_BASE_URL=${MODEL_BASE_URL}"
  fi
fi
echo ">>> Deploying $API_SERVICE"
gcloud run deploy "$API_SERVICE" \
  --image="$IMAGE_API" --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --execution-environment=gen2 \
  --add-cloudsql-instances="$INSTANCE_CONN" \
  --memory="$API_MEMORY" --cpu="$API_CPU" --max-instances="$MAX_INSTANCES" \
  --timeout=300 \
  --set-env-vars="$API_ENV" \
  --set-secrets="$API_SECRETS" \
  "${AUTH_ARGS[@]}"
API_URL="$(gcloud run services describe "$API_SERVICE" --region="$REGION" --format='value(status.url)')"
echo ">>> API at $API_URL"

# ---- 7. Migrate + seed ONCE (one-shot Job; never on cold start) --------------------
JOB_ENV="APP_ENV=production,STORAGE_BACKEND=gcs,GCS_BUCKET=${BUCKET}"
JOB_ENV="${JOB_ENV},CLOUD_SQL_INSTANCE=${INSTANCE_CONN},DB_USER=${DB_USER},DB_NAME=${DB_NAME}"
JOB_ENV="${JOB_ENV},RUN_MIGRATIONS=true,RUN_SEED=true,SERVE=false,GENERATION_PROVIDER=fake"
JOB_ENV="${JOB_ENV},SEED_DATA_DIR=/seed/northwind_ai"
if gcloud run jobs describe "$JOB_NAME" --region="$REGION" >/dev/null 2>&1; then
  gcloud run jobs update "$JOB_NAME" --image="$IMAGE_API" --region="$REGION" \
    --service-account="$SA_EMAIL" --set-cloudsql-instances="$INSTANCE_CONN" \
    --execution-environment=gen2 --memory="$API_MEMORY" --cpu="$API_CPU" \
    --max-retries=1 --task-timeout=900 \
    --set-env-vars="$JOB_ENV" --set-secrets="DB_PASSWORD=${DB_PASSWORD_SECRET}:latest"
else
  gcloud run jobs create "$JOB_NAME" --image="$IMAGE_API" --region="$REGION" \
    --service-account="$SA_EMAIL" --set-cloudsql-instances="$INSTANCE_CONN" \
    --execution-environment=gen2 --memory="$API_MEMORY" --cpu="$API_CPU" \
    --max-retries=1 --task-timeout=900 \
    --set-env-vars="$JOB_ENV" --set-secrets="DB_PASSWORD=${DB_PASSWORD_SECRET}:latest"
fi
echo ">>> Running migrate+seed job (embeds the corpus; ~2-3 min)"
gcloud run jobs execute "$JOB_NAME" --region="$REGION" --wait

# ---- 8. Build + deploy the web (NEXT_PUBLIC_API_URL inlined at build time) ----------
echo ">>> Building web image with NEXT_PUBLIC_API_URL=$API_URL"
gcloud builds submit "$FRONTEND_DIR" \
  --config="$SCRIPT_DIR/cloudbuild.web.yaml" \
  --substitutions="_API_URL=${API_URL},_IMAGE=${IMAGE_WEB}"
echo ">>> Deploying $WEB_SERVICE"
gcloud run deploy "$WEB_SERVICE" \
  --image="$IMAGE_WEB" --region="$REGION" \
  --memory=512Mi --cpu=1 --max-instances="$MAX_INSTANCES" \
  "${AUTH_ARGS[@]}"
WEB_URL="$(gcloud run services describe "$WEB_SERVICE" --region="$REGION" --format='value(status.url)')"

# ---- 9. Tighten API CORS to the web origin -----------------------------------------
gcloud run services update "$API_SERVICE" --region="$REGION" \
  --update-env-vars="CORS_ORIGINS=${WEB_URL}" >/dev/null

# ---- done --------------------------------------------------------------------------
cat <<EOF

============================================================
TrustBot deployed.
  Web (open this):  $WEB_URL
  API:              $API_URL
  Generation:       $GENERATION_PROVIDER   Public:  $ALLOW_UNAUTH

Stop the standing cost (Cloud SQL) when idle:
  gcloud sql instances patch $INSTANCE --activation-policy=NEVER   # stop
  gcloud sql instances patch $INSTANCE --activation-policy=ALWAYS  # start

Tear everything down (see deploy/gcp/README.md for the full list):
  gcloud run services delete $API_SERVICE --region=$REGION -q
  gcloud run services delete $WEB_SERVICE --region=$REGION -q
  gcloud run jobs delete $JOB_NAME --region=$REGION -q
  gcloud sql instances delete $INSTANCE -q
  gcloud storage rm -r gs://$BUCKET
  gcloud artifacts repositories delete $REPO --location=$REGION -q
  gcloud iam service-accounts delete $SA_EMAIL -q
============================================================
EOF
