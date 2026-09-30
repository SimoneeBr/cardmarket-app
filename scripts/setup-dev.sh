#!/usr/bin/env bash
# One-time local setup for development outside Docker (Python 3.12 + Node 22).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3.12}
for app in api agent; do
  $PY -m venv "apps/$app/.venv"
  "apps/$app/.venv/bin/pip" install -q --upgrade pip
  "apps/$app/.venv/bin/pip" install -q -e packages/shared -e "apps/$app[dev]"
done
apps/api/.venv/bin/pip install -q -e apps/agent        # contract tests
apps/agent/.venv/bin/playwright install chromium
npm install
echo "done. Next: ./scripts/test-db.sh && ./scripts/test-all.sh"
