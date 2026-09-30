#!/usr/bin/env bash
# Smoke test of the PRODUCTION compose file on this machine, in MOCK mode
# (never contacts Cardmarket). Uses DOMAIN=localhost (Caddy internal CA),
# random secrets and an isolated project "cmc-prodsmoke" that is removed at the end.
#
# Checks: all services healthy, only Caddy/VNC ports published, /internal and
# healthchecks not reachable from outside, HTTPS + Secure cookies, setup token,
# network isolation, Chromium under the hardened container, DB backup/restore.
set -euo pipefail
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=cmc-prodsmoke COMPOSE_FILE=docker-compose.prod.yml
ENV_FILE=$(mktemp); export ENV_FILE
rnd() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
SETUP_TOKEN=$(rnd 24)
cat > "$ENV_FILE" <<EOT
POSTGRES_PASSWORD=$(rnd 24)
AGENT_API_TOKEN=$(rnd 48)
SETUP_TOKEN=$SETUP_TOKEN
PAIRING_VNC_PASSWORD=$(rnd 12)
MOCK_CARDMARKET=true
MOCK_AUTO_PAIR=true
DOMAIN=localhost
ACME_EMAIL=admin@example.com
HTTP_PORT=${HTTP_PORT:-8080}
HTTPS_PORT=${HTTPS_PORT:-8443}
PAIRING_VNC_PORT=${PAIRING_VNC_PORT:-6380}
SYNC_INTERVAL_SECONDS=10
HEARTBEAT_SECONDS=3
EOT
DC=(docker compose --env-file "$ENV_FILE")
B="https://localhost:${HTTPS_PORT:-8443}"
BACKUP_DIR=$(mktemp -d)
cleanup() {
  if [ "${KEEP_STACK:-0}" = "1" ]; then
    echo "stack kept; env file: $ENV_FILE"
  else
    "${DC[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    rm -f "$ENV_FILE"
  fi
  rm -rf "$BACKUP_DIR"
}
trap cleanup EXIT
ok() { echo "  ✓ $*"; }
die() { echo "  ✗ $*" >&2; exit 1; }

echo "== missing secrets are refused"
docker compose --env-file /dev/null config -q 2>/dev/null && die "config accepted without secrets"
ok "compose refuses to render without secrets"

echo "== start"
"${DC[@]}" up -d --build --wait >/dev/null
for s in postgres api agent web caddy; do
  [ "$(docker inspect "${COMPOSE_PROJECT_NAME}-$s-1" --format '{{.State.Health.Status}}')" = healthy ] || die "$s not healthy"
done
ok "all services healthy"

echo "== published ports"
ports=$("${DC[@]}" ps --format '{{.Service}} {{.Publishers}}')
echo "$ports" | grep -E '^(postgres|api|web) .*PublishedPort:[1-9]' && die "internal service published on host"
[[ "$(echo "$ports" | grep '^agent')" == *127.0.0.1* ]] || die "VNC not bound to 127.0.0.1"
ok "only caddy (80/443) and VNC on 127.0.0.1"

echo "== routing"
for p in /internal/agent/heartbeat /healthz /health/ready /api/docs /api/openapi.json; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' "$B$p"); [ "$code" = 404 ] || die "$p returned $code"
done
ok "internal endpoints, healthchecks and API docs not public"
[ "$(curl -sk -o /dev/null -w '%{http_code}' "$B/api/setup/status")" = 200 ] || die "API not reachable via Caddy"
[ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${HTTP_PORT:-8080}/")" = 308 ] || die "HTTP not redirected"
ok "API/web via HTTPS, HTTP redirects"

echo "== first-run setup"
body='{"email":"smoke@example.com","name":"Smoke","password":"smoke-password-2026"'
[ "$(curl -sk -o /dev/null -w '%{http_code}' -X POST "$B/api/setup/admin" -H 'content-type: application/json' -d "$body}")" = 403 ] || die "setup without token accepted"
headers=$(curl -sk -D - -o /dev/null -X POST "$B/api/setup/admin" -H 'content-type: application/json' -d "$body,\"setup_token\":\"$SETUP_TOKEN\"}")
[[ "$headers" == *"HTTP/2 201"* ]] || die "setup with token failed"
echo "$headers" | grep -i 'set-cookie: cmc_session' | grep 'Secure' | grep 'HttpOnly' >/dev/null || die "session cookie not Secure/HttpOnly"
echo "$headers" | grep -i 'strict-transport-security' >/dev/null || die "HSTS missing"
ok "setup token enforced, Secure/HttpOnly cookies, HSTS"

echo "== isolation"
"${DC[@]}" exec -T agent python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('postgres', 5432))" 2>/dev/null && die "agent can reach postgres"
"${DC[@]}" exec -T postgres wget -q -T 5 -O /dev/null https://example.com 2>/dev/null && die "postgres has Internet access"
ok "db network internal-only"

echo "== chromium in hardened container (no network access to Cardmarket)"
# (capture first: `cmd | grep -q` + pipefail fails on SIGPIPE even when it matches)
out=$("${DC[@]}" run --rm --no-deps agent browser-selftest 2>/dev/null || true)
[[ "$out" == *'"chromium": "ok"'* ]] || die "headless chromium: $out"
out=$("${DC[@]}" run --rm --no-deps -e HEADLESS=false agent browser-selftest 2>/dev/null || true)
[[ "$out" == *'"chromium": "ok"'* ]] || die "headed chromium (pairing): $out"
ok "chromium headless + headed (Xvfb) with cap_drop ALL / no-new-privileges"

echo "== backup / restore"
count() {
  "${DC[@]}" exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F/ -c "select (select count(*) from orders), (select count(*) from messages), (select count(*) from audit_logs), (select count(*) from action_queue)"'
}
before=$(count)
[ -n "$before" ] || die "cannot count rows"
dump=$(./scripts/backup-db.sh "$BACKUP_DIR" | tail -1 | cut -d' ' -f1)
[ -s "$dump" ] || die "backup file missing"
"${DC[@]}" exec -T postgres sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "truncate orders, conversations, audit_logs, action_queue cascade"' >/dev/null 2>&1
./scripts/restore-db.sh "$dump" --yes >/dev/null 2>&1
after=$(count)
[ "$before" = "$after" ] || die "restore mismatch: $before vs $after"
ok "restored orders/messages/audit/actions = $after"

echo "PROD SMOKE TEST PASSED"
