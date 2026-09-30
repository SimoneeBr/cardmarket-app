# Test

- `apps/api/tests/unit` · `apps/api/tests/integration` — API, database, auth/permessi, sync engine, action queue, notifiche, **contratto agent↔API** (runner reale + PostgreSQL reale).
- `apps/agent/tests` — parser (fixture HTML), mock adapter, executor execute→verify, sync incrementale, runner, **Chromium reale** contro un finto sito Cardmarket locale.
- `apps/web/src/**/*.test.ts(x)` — Vitest.
- `tests/e2e` — Playwright E2E su stack Docker mock (`./scripts/e2e.sh`).

Tutto: `./scripts/test-all.sh` + `./scripts/e2e.sh`. Nessun test usa il sito Cardmarket reale.
