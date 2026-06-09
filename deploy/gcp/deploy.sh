#!/usr/bin/env bash
#
# Deploy TrustBot to Google Cloud Run + Cloud SQL + GCS + Secret Manager.
#
# Parameterized and idempotent: every step guards on existence, so re-running after a
# failure is safe. PROJECT_ID is never hardcoded — it comes from the environment. Secret
# Manager secrets are referenced BY NAME (--set-secrets / in-process for the SQL user
# password); their values are never printed, logged, or committed (note: no `set -x`).
#
# Least privilege (docs/10 Phase A; full grant list in deploy/gcp/README.md): three distinct
# service accounts — the public API service, the one-shot migrate/seed Job, and the build-time
# Cloud Build identity — each scoped to only what it needs (per-secret, one-bucket object
# access, Cloud SQL client). No Editor/Owner, no project-wide wildcards, and builds no longer
# run as the broad Compute Engine default SA.
#
# Defaults deploy the PUBLIC, no-LLM demo: GENERATION_PROVIDER=fake on a public URL, so
# there is no API key in front of an open endpoint (the runtime SA isn't even granted the
# model-key secret). Override the vars below for a future IAP-gated real-model instance
# (GENERATION_PROVIDER=anthropic + trustbot-llm-key + ALLOW_UNAUTH=false).
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
# Three distinct least-privilege identities (blast-radius isolation): the public API service,
# the one-shot migrate/seed Job, and the build-time Cloud Build identity each get only what
# they need — a compromise of one cannot act as the others.
SA_NAME="${SA_NAME:-trustbot-run}"                    # API runtime SA (Cloud Run service)
JOB_SA_NAME="${JOB_SA_NAME:-trustbot-job}"            # migrate/seed Job SA (one-shot, not public)
BUILD_SA_NAME="${BUILD_SA_NAME:-trustbot-build}"      # Cloud Build SA (build-time only)
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
JOB_SA_EMAIL="${JOB_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA_EMAIL="${BUILD_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA_REF="projects/${PROJECT_ID}/serviceAccounts/${BUILD_SA_EMAIL}"

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

# ---- 4. Least-privilege service accounts (the exact grants are documented in README.md) -
# Helpers — each binding is resource-scoped where the role allows it (per-secret, one-bucket),
# project-level only where a role has no resource scope (Cloud SQL Client). Retried because a
# just-created service account can take a moment to be usable as an IAM member.
ensure_sa() {  # $1=account-id  $2=display-name
  local email="${1}@${PROJECT_ID}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$email" >/dev/null 2>&1; then
    echo ">>> Creating service account $email"
    gcloud iam service-accounts create "$1" --display-name="$2"
  fi
}
grant_secret() {  # $1=secret-name  $2=sa-email — Secret Accessor on ONE secret (resource-level)
  retry gcloud secrets add-iam-policy-binding "$1" \
    --member="serviceAccount:$2" --role=roles/secretmanager.secretAccessor >/dev/null
}
grant_sql_client() {  # $1=sa-email — minimal role to open the Cloud SQL socket (no resource scope)
  retry gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$1" --role=roles/cloudsql.client --condition=None >/dev/null
}
grant_bucket_objects() {  # $1=sa-email — read+write OBJECTS on the ONE bucket (not bucket admin)
  retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member="serviceAccount:$1" --role=roles/storage.objectUser >/dev/null
}

ensure_sa "$SA_NAME"       "TrustBot API runtime"
ensure_sa "$JOB_SA_NAME"   "TrustBot migrate/seed job"
ensure_sa "$BUILD_SA_NAME" "TrustBot Cloud Build"

# API runtime SA (the public service): DB client + DB-password secret + bucket objects. The
# model key is granted ONLY for a real-model deploy — the fake demo never receives it (least
# privilege: don't hand an open public endpoint access to a key it never uses).
grant_sql_client "$SA_EMAIL"
grant_secret "$DB_PASSWORD_SECRET" "$SA_EMAIL"
grant_bucket_objects "$SA_EMAIL"
if [ "$GENERATION_PROVIDER" != "fake" ]; then
  grant_secret "$LLM_KEY_SECRET" "$SA_EMAIL"
fi

# Migrate/seed Job SA (one-shot, not internet-facing): the same data-plane needs, but NEVER
# the model key (the Job always runs GENERATION_PROVIDER=fake).
grant_sql_client "$JOB_SA_EMAIL"
grant_secret "$DB_PASSWORD_SECRET" "$JOB_SA_EMAIL"
grant_bucket_objects "$JOB_SA_EMAIL"

# Cloud Build SA: a dedicated build-time identity (push images, write build logs) — so builds
# do NOT run as the broad Compute Engine default SA, and the build identity has zero runtime
# data access. The builder role bundles the logging + Artifact Registry + cloudbuild-bucket
# permissions a build needs; builds run as this SA via `--service-account` below.
retry gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA_EMAIL" \
  --role=roles/cloudbuild.builds.builder --condition=None >/dev/null
# The principal running this script must be able to actAs the build SA for `builds submit
# --service-account`. Grant it explicitly (idempotent; project Owners already have it via
# their role). Best-effort: an Owner deploy works without it, so a failure here only warns.
OPERATOR="$(gcloud config get-value account 2>/dev/null || true)"
if [ -n "$OPERATOR" ]; then
  case "$OPERATOR" in
    *.gserviceaccount.com) OPERATOR_MEMBER="serviceAccount:$OPERATOR" ;;
    *)                     OPERATOR_MEMBER="user:$OPERATOR" ;;
  esac
  gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA_EMAIL" \
    --member="$OPERATOR_MEMBER" --role=roles/iam.serviceAccountUser >/dev/null 2>&1 \
    || echo "  (note: ensure '$OPERATOR' can actAs $BUILD_SA_EMAIL — Owners already can)"
fi

# ---- 5. Build + push the API image (bakes the model; stage the seed into the image) -
echo ">>> Building API image (first build downloads the model, ~10-15 min)"
cp -R "$SEED_DIR/." "$BACKEND_DIR/seed_bundle/"
# Build as the dedicated build SA (not the Compute Engine default SA). A user-specified build
# SA can't use the legacy default log bucket, so use a regional project-owned bucket.
gcloud builds submit "$BACKEND_DIR" --tag "$IMAGE_API" --timeout=3600 \
  --service-account="$BUILD_SA_REF" \
  --default-buckets-behavior=regional-user-owned-bucket
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
# Runs as the dedicated Job SA (not the API runtime SA): only DB password + bucket objects,
# never the model key.
if gcloud run jobs describe "$JOB_NAME" --region="$REGION" >/dev/null 2>&1; then
  gcloud run jobs update "$JOB_NAME" --image="$IMAGE_API" --region="$REGION" \
    --service-account="$JOB_SA_EMAIL" --set-cloudsql-instances="$INSTANCE_CONN" \
    --execution-environment=gen2 --memory="$API_MEMORY" --cpu="$API_CPU" \
    --max-retries=1 --task-timeout=900 \
    --set-env-vars="$JOB_ENV" --set-secrets="DB_PASSWORD=${DB_PASSWORD_SECRET}:latest"
else
  gcloud run jobs create "$JOB_NAME" --image="$IMAGE_API" --region="$REGION" \
    --service-account="$JOB_SA_EMAIL" --set-cloudsql-instances="$INSTANCE_CONN" \
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
  --substitutions="_API_URL=${API_URL},_IMAGE=${IMAGE_WEB}" \
  --service-account="$BUILD_SA_REF" \
  --default-buckets-behavior=regional-user-owned-bucket
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
  gcloud iam service-accounts delete $JOB_SA_EMAIL -q
  gcloud iam service-accounts delete $BUILD_SA_EMAIL -q
============================================================
EOF
