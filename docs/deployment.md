# Deployment

## Topologia consigliata (singolo host)

```
Internet → Caddy (HTTPS automatico) ─┬─ /api/*  → api:8000
                                     ├─ /internal/* → 404
                                     └─ /*      → web:3000
            api → postgres
            agent → api (rete privata Docker) → www.cardmarket.com
```

Una VM basta per un negozio:

| Risorsa | Minimo | Consigliato |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU (Chromium) |
| RAM | 3 GB | 4–8 GB |
| Disco | 20 GB | 40 GB SSD (immagine agent ~2 GB, DB, artifact) |
| OS | Linux x86_64/arm64 con Docker Compose v2 | |

L'agent può girare anche su un'altra macchina: serve solo che raggiunga `API_URL` in rete privata/VPN (non esporre `/internal` su Internet).

## Procedura

```bash
git clone <repo> && cd cardmarket-companion
cp .env.example .env
# Modifica .env:
#   ENVIRONMENT=production   COOKIE_SECURE=true   DOMAIN=companion.tuonegozio.it
#   POSTGRES_PASSWORD=<forte>  AGENT_API_TOKEN=<>=32 caratteri casuali>
#   MOCK_CARDMARKET=false (quando pronto)  VAPID_* (push)  SEED_ON_START=true
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
- L'API rifiuta di avviarsi in produzione con token agent corto o `COOKIE_SECURE=false`.
- OpenAPI/Swagger sono disattivati in produzione.
- Migrazioni: eseguite automaticamente all'avvio del container API (`alembic upgrade head`).
- Chiavi push: `docker compose run --rm api python -m app.scripts.generate_vapid`.

## Variabili d'ambiente

Tutte documentate in `.env.example`. Obbligatorie in produzione: `ENVIRONMENT`, `COOKIE_SECURE`, `DOMAIN`, `POSTGRES_PASSWORD`, `AGENT_API_TOKEN`. Consigliate: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `PAIRING_VIEWER_URL`, `RETENTION_*`.

## Volumi persistenti

| Volume | Contenuto | Se perso |
|---|---|---|
| `pgdata` | database | perdita dati locali (ricostruibili in parte dal sync) |
| `browser-profile` → `/data/browser-profile` | **sessione Cardmarket** | serve un nuovo pairing |
| `agent-artifacts` | screenshot/trace | nessun impatto |
| `mock-state` | stato del mock | nessun impatto |
| `caddy-data` | certificati TLS | rinnovo automatico |

**Il profilo browser deve sopravvivere ai deploy**: non usare `docker compose down -v` in produzione.

## Backup

```bash
# Database (giornaliero, via cron)
docker compose exec -T postgres pg_dump -U cmc -Fc cmc > backup-$(date +%F).dump
# Ripristino
docker compose exec -T postgres pg_restore -U cmc -d cmc --clean < backup.dump
```
Profilo browser: vedi `cardmarket-agent.md#backup-del-profilo-browser`. Cifra i backup: contengono dati dei clienti e la sessione.

## Aggiornamenti

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
Le azioni in coda sono persistenti: un riavvio non le perde (quelle interrotte vengono verificate prima di essere ripetute).

## Health check

- API: `GET /health/live`, `GET /health/ready` (verifica DB) — usati dal healthcheck Docker.
- Web: healthcheck sul manifest; Agent: processo attivo + "Ultimo contatto agent" nella UI (offline dopo `AGENT_OFFLINE_AFTER_SECONDS`, default 120 s).
