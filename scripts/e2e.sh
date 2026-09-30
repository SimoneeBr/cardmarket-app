#!/usr/bin/env bash
# Runs the E2E suite against a fresh, isolated mock stack (project "cmc-e2e").
set -euo pipefail
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=cmc-e2e
export WEB_PORT=${WEB_PORT:-3100} API_PORT=${API_PORT:-8100} PAIRING_VNC_PORT=${PAIRING_VNC_PORT:-6180}
export MOCK_CARDMARKET=true MOCK_ACTIVITY_RATE=0 SYNC_INTERVAL_SECONDS=10 HEARTBEAT_SECONDS=3 LOG_FORMAT=console

cleanup() { [ "${KEEP_STACK:-0}" = "1" ] || docker compose down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker compose up -d --build --wait
npm run install-browsers -w @cmc/e2e >/dev/null
E2E_BASE_URL="http://localhost:${WEB_PORT}" npm run test -w @cmc/e2e -- "$@"
