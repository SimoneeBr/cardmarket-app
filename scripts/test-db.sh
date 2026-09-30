#!/usr/bin/env bash
# Starts a throwaway PostgreSQL for the API integration tests (port 55432).
set -euo pipefail
if ! docker ps --format '{{.Names}}' | grep -q '^cmc-test-pg$'; then
  docker rm -f cmc-test-pg >/dev/null 2>&1 || true
  docker run -d --name cmc-test-pg -e POSTGRES_USER=cmc -e POSTGRES_PASSWORD=cmc \
    -e POSTGRES_DB=cmc_test -p 55432:5432 postgres:17-alpine >/dev/null
fi
until docker exec cmc-test-pg pg_isready -U cmc -d cmc_test >/dev/null 2>&1; do sleep 1; done
echo "test database ready: postgresql+psycopg://cmc:cmc@localhost:55432/cmc_test"
