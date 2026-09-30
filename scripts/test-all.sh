#!/usr/bin/env bash
# Lint + type-check + all unit/integration/browser tests (E2E: scripts/e2e.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/check-repo-hygiene.sh
./scripts/test-db.sh
echo "== api";   (cd apps/api   && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app && .venv/bin/pytest)
echo "== agent"; (cd apps/agent && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy agent && .venv/bin/pytest)
echo "== web";   (cd apps/web   && npx tsc --noEmit && npx eslint . && npx vitest run)
echo "ALL CHECKS PASSED"
