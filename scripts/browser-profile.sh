#!/usr/bin/env bash
# Manage the agent's browser profile volume. The profile IS A CREDENTIAL:
# it contains the authenticated Cardmarket session cookies.
#
#   ./scripts/browser-profile.sh backup  <out-dir>   # encrypted (gpg, symmetric AES256)
#   ./scripts/browser-profile.sh restore <file.gpg> --yes
#   ./scripts/browser-profile.sh destroy --yes       # forget the session locally
#
# The agent is stopped while the profile is read/written (Chromium locks it).
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.prod.yml}
DC=(docker compose -f "$COMPOSE_FILE" ${COMPOSE_PROJECT_NAME:+-p "$COMPOSE_PROJECT_NAME"} ${ENV_FILE:+--env-file "$ENV_FILE"})
PROJECT=$("${DC[@]}" config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
VOLUME="${PROJECT}_browser-profile"
command -v gpg >/dev/null || { echo "gpg is required (profile backups are always encrypted)" >&2; exit 1; }
# Non-interactive use: PROFILE_PASSPHRASE_FILE=/root/.cmc-profile-pass (mode 600).
GPG=(gpg --quiet)
if [ -n "${PROFILE_PASSPHRASE_FILE:-}" ]; then
  GPG+=(--batch --pinentry-mode loopback --passphrase-file "$PROFILE_PASSPHRASE_FILE")
fi

case "${1:-}" in
  backup)
    OUT_DIR=${2:?usage: browser-profile.sh backup <out-dir>}
    mkdir -p "$OUT_DIR" && chmod 700 "$OUT_DIR"
    FILE="$OUT_DIR/browser-profile-$(date -u +%Y%m%dT%H%M%SZ).tgz.gpg"
    umask 077
    "${DC[@]}" stop agent >&2
    trap '"${DC[@]}" start agent >&2' EXIT
    docker run --rm --network none -v "$VOLUME":/p:ro alpine tar czf - -C /p . \
      | "${GPG[@]}" --symmetric --cipher-algo AES256 --output "$FILE"
    echo "$FILE"
    ;;
  restore)
    FILE=${2:?usage: browser-profile.sh restore <file.gpg> --yes}
    [ "${3:-}" = "--yes" ] || { echo "refusing without --yes (replaces the current session)" >&2; exit 1; }
    "${DC[@]}" stop agent >&2
    trap '"${DC[@]}" start agent >&2' EXIT
    "${GPG[@]}" --decrypt "$FILE" | docker run --rm -i --network none -v "$VOLUME":/p alpine \
      sh -c 'find /p -mindepth 1 -delete && tar xzf - -C /p && chown -R 1001:1001 /p && chmod 700 /p'
    echo "restored into $VOLUME"
    ;;
  destroy)
    [ "${2:-}" = "--yes" ] || { echo "refusing without --yes (a new pairing will be required)" >&2; exit 1; }
    "${DC[@]}" stop agent >&2
    docker run --rm --network none -v "$VOLUME":/p alpine sh -c 'find /p -mindepth 1 -delete'
    "${DC[@]}" start agent >&2
    echo "browser profile wiped: the agent will report AUTH_REQUIRED until a new pairing."
    echo "Also end the session on Cardmarket itself (see docs/cardmarket-agent.md)."
    ;;
  *)
    sed -n '2,10p' "$0"; exit 1 ;;
esac
