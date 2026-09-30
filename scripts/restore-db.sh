#!/usr/bin/env bash
# Restores a dump produced by backup-db.sh. DESTRUCTIVE: replaces current data.
#
#   ./scripts/restore-db.sh backups/cmc-db-XXXX.dump --yes
#
# The agent and api are stopped during the restore so no sync/action runs
# against a half-restored database; they are started again afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."
FILE=${1:?usage: restore-db.sh <dump-file> --yes}
[ "${2:-}" = "--yes" ] || { echo "refusing to restore without --yes (this replaces all data)" >&2; exit 1; }
[ -s "$FILE" ] || { echo "dump not found or empty: $FILE" >&2; exit 1; }
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.prod.yml}
DC=(docker compose -f "$COMPOSE_FILE" ${COMPOSE_PROJECT_NAME:+-p "$COMPOSE_PROJECT_NAME"} ${ENV_FILE:+--env-file "$ENV_FILE"})

"${DC[@]}" stop agent api
"${DC[@]}" exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction' < "$FILE"
"${DC[@]}" start api agent
echo "restored $FILE"
