# Sviluppo locale

## Solo Docker (consigliato per provare l'app)

```bash
docker compose up --build        # http://localhost:3000
```
Mock mode di default. Primo accesso: la procedura guidata `/setup` crea l'amministratore.

## Sviluppo dei singoli servizi

Prerequisiti: Python 3.12, Node 22, Docker.

```bash
./scripts/setup-dev.sh           # venv api/agent, Chromium, npm install
./scripts/test-db.sh             # PostgreSQL di test su :55432
docker compose up -d postgres    # DB di sviluppo (oppure usa quello di test)
```

API:
```bash
cd apps/api
export DATABASE_URL=postgresql+psycopg://cmc:cmc@localhost:55432/cmc_test COOKIE_SECURE=false \
       AGENT_API_TOKEN=dev-token-dev-token-dev-token-dev LOG_FORMAT=console
.venv/bin/alembic upgrade head
.venv/bin/python -m app.scripts.seed --demo-users   # template + manager/staff demo
.venv/bin/uvicorn app.main:app --reload             # docs: http://localhost:8000/api/docs
```

Agent (mock):
```bash
cd apps/agent
API_URL=http://localhost:8000 AGENT_API_TOKEN=dev-token-dev-token-dev-token-dev \
MOCK_STATE_FILE=./.mock/state.json LOG_FORMAT=console .venv/bin/python -m agent
```

Web:
```bash
API_INTERNAL_URL=http://localhost:8000 npm run dev:web   # http://localhost:3000
```

Dopo aver modificato gli schemi Pydantic dell'API: `npm run gen:types` (rigenera `packages/types/src/api.ts`).
Nuova migrazione: `cd apps/api && .venv/bin/alembic revision --autogenerate -m "..."`, poi rivedila.

## Test

| Comando | Cosa |
|---|---|
| `./scripts/test-all.sh` | lint (ruff, eslint), format check, mypy strict, tsc, tutti i test Python e Vitest |
| `cd apps/api && .venv/bin/pytest` | unit + integration su PostgreSQL reale (migrazioni Alembic incluse) + contratto agent↔API |
| `cd apps/agent && .venv/bin/pytest` | parser su fixture, mock adapter, executor, sync, runner, **Chromium reale** contro un finto sito Cardmarket locale |
| `npm run test:web` | Vitest + Testing Library |
| `./scripts/e2e.sh` | stack Docker isolato (`cmc-e2e`, porte 3100/8100) + Playwright mobile e desktop |

Nessun test contatta il sito Cardmarket reale.

## Convenzioni

- Python: ruff (lint+format, 100 colonne), mypy `strict`; TypeScript `strict` + `noUncheckedIndexedAccess`, ESLint next.
- Nessun selettore/URL Cardmarket fuori da `apps/agent/agent/cardmarket/{selectors,urls}.py`.
- Nessun enum/modello duplicato: Python in `cmc_shared`, TypeScript generato.
- Log strutturati JSON con `request_id`, `sync_id`, `action_id`, `correlation_id` (request id della richiesta utente che ha creato l'azione).
