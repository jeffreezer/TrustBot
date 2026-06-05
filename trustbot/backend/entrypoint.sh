#!/bin/sh
# Container start: migrate → seed (idempotent) → serve.
# The seed is retried to absorb DB/object-store startup races; because it is
# idempotent, retries are safe and a second container start just skips seeding.
set -e

echo "[entrypoint] applying database migrations..."
alembic upgrade head

echo "[entrypoint] seeding demo data (idempotent)..."
i=1
while [ "$i" -le 5 ]; do
  if python -m app.seed; then
    break
  fi
  echo "[entrypoint] seed attempt $i failed; retrying in 3s..."
  i=$((i + 1))
  sleep 3
done

echo "[entrypoint] starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
