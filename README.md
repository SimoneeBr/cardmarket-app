# Cardmarket Companion

Applicazione web **mobile-first (PWA)**, privata e **non ufficiale**, per gestire dal telefono le operazioni quotidiane di un negozio su Cardmarket: ordini, chat con gli acquirenti, carrelli, notifiche.

L'integrazione con Cardmarket avviene tramite un **browser agent** (Playwright + Chromium, profilo persistente) che usa il sito come un normale browser: nessuna API ufficiale, nessuna password Cardmarket salvata, 2FA mai aggirata. I dipendenti accedono solo all'app, con ruoli Admin / Manager / Staff.

```
web (Next.js PWA) ──/api──▶ api (FastAPI + PostgreSQL) ◀──/internal── agent (Playwright) ──▶ cardmarket.com
```

Principio guida: **meglio non eseguire un'azione che eseguirla sull'ordine o sulla conversazione sbagliati**. Ogni scrittura viene verificata su Cardmarket prima di essere dichiarata riuscita.

---

## Avvio rapido (mock, nessun account Cardmarket necessario)

Prerequisiti: Docker Desktop / Docker Engine con Compose v2.

```bash
git clone <repo> cardmarket-companion && cd cardmarket-companion
cp .env.example .env            # facoltativo: i default funzionano in locale
docker compose up --build
```

1. Apri **http://localhost:3000** → procedura di primo avvio `/setup`: crea l'amministratore.
2. L'agent mock è già collegato e sincronizza un negozio simulato (24 ordini, 12 chat, 12 carrelli) che evolve nel tempo.
3. API e documentazione OpenAPI: http://localhost:8000/api/docs

Migrazioni e seed (template messaggi predefiniti) vengono eseguiti automaticamente all'avvio del container API. Utenti demo aggiuntivi: `docker compose exec api python -m app.scripts.seed --demo-users`.

### Cosa provare in mock mode
- Dashboard con contatori operativi e attività recenti (aggiornamento automatico).
- Ordini: filtri, ricerca (anche per nome carta), dettaglio, **Segna come spedito** con tracking.
- Chat: inbox, conversazione collegata all'ordine, template con variabili, invio (stato `In invio… → ✓` solo dopo verifica).
- Impostazioni → Connessione → **Simulazioni**: sessione scaduta (poi *Avvia collegamento*), errore di sync, nuova attività (→ notifiche).
- Scrivi un messaggio contenente `[mock:unverified]` o `[mock:fail]` per vedere gli stati `Esito da verificare` / retry.

## Collegare Cardmarket reale

> Selettori e URL dell'adapter reale sono predisposti ma **non ancora verificati** su una sessione reale (`TODO: VERIFY AGAINST LIVE CARDMARKET`). Finché non vengono calibrati, le letture falliscono in sicurezza e le scritture sono bloccate. Vedi [docs/cardmarket-agent.md](docs/cardmarket-agent.md#calibrazione-e-aggiornamento-dei-selettori).

1. In `.env`: `MOCK_CARDMARKET=false`, `PAIRING_VNC_ENABLED=true`, `PAIRING_VNC_PASSWORD=<password>`.
2. `docker compose up -d --build`
3. App → Impostazioni → Connessione Cardmarket → **Avvia collegamento**.
4. Apri `http://localhost:6080/vnc.html` (da remoto via `ssh -L 6080:localhost:6080`), fai **tu** login e 2FA.
5. L'agent rileva la sessione, la salva nel volume `browser-profile` e passa a `CONNECTED`.
6. `docker compose run --rm agent calibrate` per verificare/aggiornare i selettori.

## Produzione

```bash
cp .env.example .env   # ENVIRONMENT=production, COOKIE_SECURE=true, DOMAIN, segreti forti
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
Caddy fornisce HTTPS automatico; `/internal/*` non è mai esposto. Il volume `browser-profile` **deve** essere persistente e salvato nei backup. Dettagli: [docs/deployment.md](docs/deployment.md).

## Sviluppo e test

```bash
./scripts/setup-dev.sh   # venv Python, Chromium, npm
./scripts/test-all.sh    # lint, format, mypy strict, tsc, pytest (PostgreSQL reale), Vitest
./scripts/e2e.sh         # stack isolato + Playwright E2E (mobile e desktop)
```
Dettagli: [docs/development.md](docs/development.md).

## Struttura

```
apps/api        FastAPI · SQLAlchemy · Alembic · sync engine · action queue · notifiche · audit
apps/agent      runner · executor (execute→verify) · adapter mock · adapter Playwright (agent/cardmarket/)
apps/web        Next.js 16 · React 19 · TanStack Query · Tailwind 4 · PWA
packages/shared contratti Python condivisi (enum, modelli normalizzati, protocollo agent↔API)
packages/types  tipi TypeScript generati dall'OpenAPI
infrastructure  Dockerfile, entrypoint, Caddy
tests/e2e       Playwright E2E
docs/           architecture · development · deployment · cardmarket-agent · security · troubleshooting
```

## Documentazione
- [Architettura e decisioni](docs/architecture.md)
- [Browser agent: pairing, sessione, action queue, selettori, backup](docs/cardmarket-agent.md)
- [Sicurezza e privacy](docs/security.md)
- [Deployment](docs/deployment.md) · [Sviluppo](docs/development.md) · [Troubleshooting](docs/troubleshooting.md)

---
Progetto non affiliato né approvato da Cardmarket. Usalo nel rispetto dei termini di servizio di Cardmarket.
