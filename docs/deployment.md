# Deployment (single host)

## Topologia

```
Internet ──80/443──▶ caddy ─┬─ /api/*                        → api:8000 ──(rete "db", internal)──▶ postgres
                            ├─ /internal/*, /healthz, /health → 404
                            └─ /*                             → web:3000 → api
                     agent ──▶ api (rete "app")      agent ──▶ www.cardmarket.com
127.0.0.1:6080 ◀── noVNC (solo pairing, via tunnel SSH)
```

- **Solo Caddy** pubblica porte (80/443). PostgreSQL, API e web non sono raggiungibili dall'host.
- PostgreSQL è su una rete `internal` senza accesso a Internet e non raggiungibile da web/agent/caddy.
- Il viewer noVNC del pairing è pubblicato solo su `127.0.0.1`.

`docker-compose.prod.yml` è un file **autonomo** (non un overlay del file di sviluppo): nessun default per i segreti, `ENVIRONMENT=production`, `COOKIE_SECURE=true`, `SEED_ON_START=false`, `DEBUG_CAPTURE_HTML=false` fissati nel file.

| Risorsa | Minimo | Consigliato |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 GB | 8 GB (limiti: agent 2 GB, postgres 1 GB, api 768 MB, web 512 MB, caddy 256 MB) |
| Disco | 20 GB | 40 GB SSD (immagine agent ~2 GB, log ruotati ≤ ~350 MB) |

## Prima installazione

```bash
git clone <repo> cardmarket-companion && cd cardmarket-companion
cp .env.example .env && chmod 600 .env
```
Imposta in `.env` tutte le voci `[PROD REQUIRED]`:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # POSTGRES_PASSWORD (URL-safe)
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # AGENT_API_TOKEN
python3 -c "import secrets; print(secrets.token_urlsafe(6))"    # PAIRING_VNC_PASSWORD
# DOMAIN, ACME_EMAIL, MOCK_CARDMARKET=true (primo avvio di verifica) o false
```
Il DNS di `DOMAIN` deve puntare al server e le porte 80/443 devono essere aperte (certificato Let's Encrypt automatico).

```bash
docker compose -f docker-compose.prod.yml up -d --build --wait
docker compose -f docker-compose.prod.yml exec api python -m app.scripts.seed          # template predefiniti (una volta)
docker compose -f docker-compose.prod.yml exec api python -m app.scripts.create_admin --email tu@negozio.it
```
Il wizard web `/setup` è **disattivato** in produzione: chiunque arrivasse per primo sul sito potrebbe altrimenti prendersi l'account admin. In alternativa imposta `SETUP_TOKEN` (≥ 16 caratteri casuali): il wizard lo richiederà. Dopo la creazione dell'admin rimuovilo.

L'API **rifiuta di avviarsi** se in produzione trova: token agent < 32 caratteri o segnaposto, password DB segnaposto, `COOKIE_SECURE=false`, `SETUP_TOKEN` debole. Docker Compose rifiuta di partire se manca un segreto.

Chiavi Web Push (facoltative): `docker compose -f docker-compose.prod.yml run --rm --no-deps api python -m app.scripts.generate_vapid` → copia in `.env` → `up -d`.

## Verifica prima di andare online

```bash
./scripts/prod-smoke.sh
```
Avvia il file di produzione in un progetto isolato (mock, `DOMAIN=localhost`, segreti casuali) e verifica: healthcheck di tutti i servizi, porte pubblicate, endpoint interni non pubblici, HTTPS + cookie `Secure`/`HttpOnly` + HSTS, setup token, isolamento di rete, Chromium headless e visibile sotto l'hardening, backup/restore del DB. Lo stesso test gira in CI.

## Healthcheck

| Servizio | Controllo | Unhealthy se |
|---|---|---|
| postgres | `pg_isready` | DB non accetta connessioni |
| api | `GET /health/ready` (query al DB) | DB irraggiungibile o API bloccata |
| web | `GET /healthz` (route dinamica + ping API) | server Next bloccato o API irraggiungibile |
| agent | `python -m agent healthcheck` | event loop fermo da > 60 s o nessun contatto riuscito con l'API da > 5 min |
| caddy | admin API `/reverse_proxy/upstreams` | config non caricata |

Le dipendenze usano `condition: service_healthy` (postgres → api → agent/web → caddy). Nota: Docker Compose non riavvia i container *unhealthy* (solo quelli terminati, `restart: unless-stopped`); lo stato è visibile con `docker compose ps` e va monitorato.

## Hardening applicato

- `no-new-privileges`, `cap_drop: ALL` su tutti i servizi; aggiunte solo le capability indispensabili a postgres (CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID per l'entrypoint ufficiale) e caddy (NET_BIND_SERVICE per 80/443).
- api, web, agent girano come utenti non-root; Chromium funziona senza sandbox di kernel privilegiata (Playwright usa `--no-sandbox`; l'isolamento è il container) — verificato headless e visibile.
- Limiti di CPU, memoria e numero di processi per servizio.
- Rotazione dei log Docker (`json-file`, 10 MB × 5 file; agent 20 MB × 5). I log applicativi restano JSON.
- Nessun segreto nei Dockerfile o nelle immagini; `.env` escluso da Git e dal contesto di build (`.dockerignore`).
- Filesystem root non in sola lettura: non attivato perché Chromium, Xvfb e noVNC scrivono in varie posizioni; da valutare con tmpfs dedicati.

## Volumi

| Volume (`cardmarket-companion-prod_…`) | Contenuto | Backup |
|---|---|---|
| `pgdata` | database | **sì**, con `scripts/backup-db.sh` (non copiare la directory a caldo) |
| `browser-profile` | **credenziale**: sessione Cardmarket | separato e cifrato: [browser-profile.md](browser-profile.md) |
| `agent-artifacts` | screenshot/trace di errore (dati clienti) | no (retention breve) |
| `mock-state` | stato del mock | no |
| `caddy-data`, `caddy-config` | certificati TLS | facoltativo (si rigenerano) |

`docker compose down` è sicuro. **Mai `down -v` in produzione**: cancella database e sessione Cardmarket.

## Backup e restore del database

Il dump contiene tutto ciò che serve per ripartire: ordini e articoli sincronizzati, conversazioni e messaggi (compresi quelli inviati dall'app e il loro stato), carrelli, notifiche, **audit log**, **action queue** (azioni in coda, fallite, da verificare), sync run, utenti, template e impostazioni runtime. Non contiene il profilo browser né i segreti di `.env` (da conservare in un password manager).

```bash
./scripts/backup-db.sh /srv/backups                   # dump pg_dump -Fc, verificato, permessi 600
KEEP_DAYS=30 ./scripts/backup-db.sh /srv/backups      # + elimina i dump più vecchi di 30 giorni
./scripts/restore-db.sh /srv/backups/cmc-db-<data>.dump --yes
```
Il restore ferma agent e api, ripristina in una singola transazione e li riavvia. Cron consigliato:
```
15 3 * * * cd /srv/cardmarket-companion && KEEP_DAYS=30 ./scripts/backup-db.sh /srv/backups >> /var/log/cmc-backup.log 2>&1
```
I dump contengono dati personali dei clienti: conservali cifrati (es. disco cifrato o `gpg`) con accesso limitato, e copiali fuori dal server. Il round-trip backup → cancellazione → restore è verificato da `scripts/prod-smoke.sh`.

Dopo un restore: le azioni che risultavano `PROCESSING` vengono riprese con verifica preventiva (nessun doppio invio); la prima sincronizzazione riallinea lo stato con Cardmarket.

## Aggiornamenti

```bash
./scripts/backup-db.sh /srv/backups
git pull
docker compose -f docker-compose.prod.yml up -d --build --wait
```
Le migrazioni vengono applicate all'avvio dell'API. La coda azioni è persistente.
