# Architettura

## Panoramica

```
 Telefono / desktop (PWA)
          │  HTTPS, cookie di sessione HttpOnly + CSRF
          ▼
 ┌──────────────────┐   /api/*   ┌────────────────────────────┐
 │ web (Next.js 16) │──────────▶│ api (FastAPI)              │
 │ TanStack Query   │  proxy     │ auth · RBAC · audit         │
 │ polling 2–30 s   │            │ sync engine · event bus     │
 └──────────────────┘            │ notification engine · push │
                                 │ action queue (persistente)  │
                                 └────────────┬───────────────┘
                                   PostgreSQL │  /internal/agent/* (bearer token,
                                              │  mai esposto sul web)
                                 ┌────────────▼───────────────┐
                                 │ agent (Python)             │
                                 │ runner: heartbeat → azioni │
                                 │        → sync incrementale │
                                 │ adapter: Mock | Playwright │
                                 └────────────┬───────────────┘
                                              │ Chromium, profilo persistente
                                              ▼
                                        www.cardmarket.com
```

## Struttura del repository

| Percorso | Contenuto |
|---|---|
| `apps/api` | FastAPI, SQLAlchemy 2, Alembic (`apps/api/migrations`), test unit + integration |
| `apps/agent` | Browser agent: runner, executor azioni, adapter mock, adapter Playwright (`agent/cardmarket/`) |
| `apps/web` | Next.js (App Router) mobile-first, PWA |
| `packages/shared` | Pacchetto Python `cmc_shared`: enum, modelli normalizzati, protocollo agent↔API, logging, mapping stati, templating |
| `packages/types` | Tipi TypeScript **generati** dall'OpenAPI (`npm run gen:types`) |
| `infrastructure/docker` | Dockerfile + entrypoint; `infrastructure/caddy` reverse proxy produzione |
| `tests/e2e` | Playwright E2E (mobile + desktop) contro lo stack mock |
| `docs/` | Documentazione |

Scostamenti dalla struttura suggerita (motivati):
- **Migrazioni in `apps/api/migrations`** invece di `infrastructure/migrations`: lo schema appartiene all'API, Alembic importa i modelli; tenerle vicine evita path hack e divergenze.
- **Test unit/integration dentro ogni app** (`apps/*/tests`), E2E in `tests/e2e`: ogni servizio si testa col proprio ambiente; gli E2E attraversano tutti i servizi.
- **`packages/shared` è Python**, `packages/types` è TypeScript generato: nessuna logica duplicata a mano fra backend e frontend.

## Decisioni architetturali

### ADR-1 — L'agent non accede al database
L'agent comunica solo via HTTP con `/internal/agent/*` (token bearer). Lo schema ha un unico proprietario (API), l'agent può girare su un'altra macchina/VM con Chromium, e tutte le regole (eventi, notifiche, audit) stanno in un solo posto.

### ADR-2 — Niente Redis nell'MVP
Queue, lock e stato sono in PostgreSQL:
- **action queue**: tabella `action_queue`, claim con lock di riga sulla connessione + `FOR UPDATE SKIP LOCKED`, lease con scadenza;
- **lock di sync**: lease atomico (`UPDATE ... WHERE owner IS NULL OR expired`) sulla riga `cardmarket_connection`;
- **rate limiting**: in-process (una sola istanza API è la topologia supportata per un negozio).
Meno componenti = meno guasti. Redis si può introdurre dietro le stesse interfacce se servirà scalare orizzontalmente.

### ADR-3 — Snapshot normalizzati + diff lato API (sync incrementale)
Il parser trasforma HTML → modelli `cmc_shared.models` (mai HTML verso l'API). L'API restituisce all'avvio del ciclo le *fingerprint* dei record noti; l'agent scarica il dettaglio **solo** di ordini/chat/carrelli la cui riga di lista è cambiata, con un budget massimo per ciclo (`MAX_DETAILS_PER_SYNC`). I record rimandati non vengono inviati, così restano "cambiati" e vengono ripresi al ciclo dopo. Il sync engine è idempotente: reinviare lo stesso batch non produce modifiche né eventi.

### ADR-4 — Event bus interno + outbox
Ogni cambiamento produce un `DomainEvent` persistito (`domain_events`, alimenta anche "Ultime attività"). I subscriber (motore notifiche) girano nella stessa transazione; il web push parte **dopo il commit**. La prima sincronizzazione di un account è un *initial import*: eventi registrati, nessuna notifica (niente valanga di push).

### ADR-5 — Execute → verify, sempre
Vedi `cardmarket-agent.md`. Un'azione è `SUCCESS` solo se l'esito è stato osservato su Cardmarket. Esito non verificabile → `NEEDS_ATTENTION` (messaggio `UNKNOWN`). UI non riconosciuta o ambigua → rifiuto (`NEEDS_ATTENTION`). Dopo un crash, le write action vengono rieseguite solo dopo un controllo "verify-first" (niente doppi invii).

### ADR-6 — Serializzazione per account
Un solo processo agent per account, un solo browser context, un solo task: sync e azioni non si sovrappongono mai. In più l'API concede al massimo **una** azione `PROCESSING` per connessione.

### ADR-7 — Autenticazione applicativa con sessioni server-side
Cookie `HttpOnly`, `SameSite=Lax`, `Secure` in produzione; nel DB solo lo SHA-256 del token. CSRF double-submit (`cmc_csrf` + header `X-CSRF-Token`). Password Argon2id. RBAC applicato in ogni endpoint (`security/permissions.py`), la UI nasconde solo per comodità.

### ADR-8 — Realtime via polling
TanStack Query con intervalli adattivi (2 s quando c'è un invio in corso, 5 s nella chat aperta, 15 s dashboard, 30 s liste). Web Push per le notifiche in background. SSE/WebSocket possono essere aggiunti senza cambiare i modelli.

### ADR-9 — Proxy `/api` nel frontend
Un route handler Next inoltra `/api/*` all'API leggendo `API_INTERNAL_URL` a runtime: stessa origine (cookie first-party, niente CORS) e gli endpoint interni dell'agent restano irraggiungibili dal web. In produzione Caddy instrada `/api` direttamente all'API e blocca `/internal/*`.

## Modello dati (principale)

`users`, `user_sessions`, `notification_preferences`, `push_subscriptions`, `cardmarket_connection` (stato, liveness agent, lease di sync, comandi pendenti), `cardmarket_session` (solo *riferimento* al profilo browser), `orders`/`order_items`, `conversations`/`messages`, `carts`/`cart_items`, `domain_events`, `notifications` (una riga per destinatario), `sync_runs`, `action_queue`, `audit_logs`, `message_templates`, `app_settings`.

Tutte le tabelle di dominio hanno `connection_id`: il multi-account non richiede riscritture. Gli enum sono salvati come VARCHAR (aggiungere un valore non richiede migrazioni). Campi Cardmarket non garantiti sono nullable, con colonna `extra` JSONB per estensioni.

## Stato connessione

```
DISCONNECTED ──pair──▶ CONNECTING ──login umano──▶ CONNECTED
      ▲                                              │
      │ disconnect                  login richiesto  ▼
      └──────────────── AUTH_REQUIRED / SESSION_EXPIRED ──pair/reconnect──▶ CONNECTED
                        ERROR (pagina non riconoscibile)
```
Il passaggio a `SESSION_EXPIRED`/`AUTH_REQUIRED` emette `SessionExpired` → notifica ad Admin/Manager. Un "Disconnect" dell'admin non viene annullato da un report automatico dell'agent: serve una richiesta esplicita di pair/reconnect.

## Estensioni future

Statistiche/KPI (i dati sono già normalizzati in `orders`/`order_items`), inventario, multi-marketplace (nuovo adapter che implementa `CardmarketAdapter` e produce gli stessi modelli), risposte assistite da AI (nuovo servizio che suggerisce testo al `Composer`, l'invio resta nella action queue), automazioni (subscriber dell'event bus).
