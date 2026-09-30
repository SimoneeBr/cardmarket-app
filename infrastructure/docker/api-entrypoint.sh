#!/bin/sh
# Waits for PostgreSQL, applies migrations, optionally seeds, then starts the API.
set -eu

attempt=0
until alembic upgrade head; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    echo "database not reachable after $attempt attempts" >&2
    exit 1
  fi
  echo "waiting for database (attempt $attempt)..." >&2
  sleep 2
done

if [ "${SEED_ON_START:-true}" = "true" ]; then
  python -m app.scripts.seed ${SEED_ARGS:-}
fi

exec uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}" \
  --workers 1
