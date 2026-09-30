#!/bin/sh
# Default: wait for PostgreSQL, apply migrations, optionally seed, start the API.
# With arguments, run that command instead (e.g. `python -m app.scripts.create_admin`),
# so one-off administrative commands work with `docker compose run/exec`.
set -eu

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

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

if [ "${SEED_ON_START:-false}" = "true" ]; then
  python -m app.scripts.seed ${SEED_ARGS:-}
fi

exec uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --no-server-header \
  --workers 1
