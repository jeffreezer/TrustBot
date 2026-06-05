#!/bin/sh
# Container start. Behaviour is env-gated so one image serves three roles:
#   - local compose (defaults): migrate -> seed -> serve  (unchanged)
#   - Cloud Run serving:        RUN_MIGRATIONS=false RUN_SEED=false SERVE=true
#   - Cloud Run migrate+seed Job: RUN_MIGRATIONS=true RUN_SEED=true SERVE=false
# In production the serving container must NOT migrate or seed on cold start (a one-shot
# Job does that once); seeding embeds the corpus and must not run per-instance.
# Honors Cloud Run's $PORT (defaults to 8000 for local compose).
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[entrypoint] applying database migrations..."
  alembic upgrade head
fi

if [ "${RUN_SEED:-true}" = "true" ]; then
  echo "[entrypoint] seeding demo data (idempotent)..."
  # Retry to absorb DB/object-store startup races; idempotent, so retries are safe.
  seeded=0
  i=1
  while [ "$i" -le 5 ]; do
    if python -m app.seed; then
      seeded=1
      break
    fi
    echo "[entrypoint] seed attempt $i failed; retrying in 3s..."
    i=$((i + 1))
    sleep 3
  done
  # Fail closed: if every attempt failed (e.g. OOM), exit non-zero so the migrate-seed
  # Job is marked failed instead of silently leaving an unseeded database.
  if [ "$seeded" -ne 1 ]; then
    echo "[entrypoint] seeding failed after retries" >&2
    exit 1
  fi
fi

if [ "${SERVE:-true}" = "true" ]; then
  echo "[entrypoint] starting API on port ${PORT:-8000}..."
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi

echo "[entrypoint] SERVE=false — done (migrate/seed job)."
