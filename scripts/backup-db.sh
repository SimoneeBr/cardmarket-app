#!/usr/bin/env bash
# PostgreSQL backup (custom format, compressed) of the application database.
# Contains: orders, items, conversations/messages, carts, notifications, audit log,
# action queue, sync runs, users, templates, runtime settings.
# Does NOT contain: the browser profile (Cardmarket session) nor .env secrets.
#
#   ./scripts/backup-db.sh [output-dir]            (default: ./backups)
#   COMPOSE_FILE=docker-compose.prod.yml ./scripts/backup-db.sh /srv/backups
#
# The dump contains customer data: store it encrypted and access-restricted.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT_DIR=${1:-./backups}
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.prod.yml}
DC=(docker compose -f "$COMPOSE_FILE" ${COMPOSE_PROJECT_NAME:+-p "$COMPOSE_PROJECT_NAME"} ${ENV_FILE:+--env-file "$ENV_FILE"})

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"
FILE="$OUT_DIR/cmc-db-$(date -u +%Y%m%dT%H%M%SZ).dump"
umask 077
"${DC[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$FILE"
# Sanity check: the archive must be readable and contain the core tables.
"${DC[@]}" exec -T postgres pg_restore --list < "$FILE" | grep -q "TABLE DATA public orders" \
  || { echo "backup verification failed: $FILE" >&2; exit 1; }
echo "$FILE ($(du -h "$FILE" | cut -f1))"
# Retention (optional): KEEP_DAYS=30 ./scripts/backup-db.sh
if [ -n "${KEEP_DAYS:-}" ]; then
  find "$OUT_DIR" -name 'cmc-db-*.dump' -mtime +"$KEEP_DAYS" -delete
fi
