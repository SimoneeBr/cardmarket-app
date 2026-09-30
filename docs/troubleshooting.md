# Troubleshooting

| Sintomo | Causa probabile | Cosa fare |
|---|---|---|
| Banner "agent offline" | container agent fermo o non raggiunge l'API | `docker compose ps`, `docker compose logs agent`; verifica `AGENT_API_TOKEN` uguale in api e agent |
| "Sessione Cardmarket scaduta" / "Autenticazione richiesta" | Cardmarket ha chiesto un nuovo login | Impostazioni → Connessione → **Riconnetti**; se resta, **Avvia collegamento** (pairing) |
| Pairing in timeout | nessuno ha completato il login entro `PAIRING_TIMEOUT_SECONDS` | abilita noVNC (`PAIRING_VNC_ENABLED`), apri il viewer e ripeti |
| Errore `CARDMARKET_CHANGED` | pagina non riconosciuta (layout cambiato o selettori non calibrati) | guarda lo screenshot in Operazioni → Errori; esegui `docker compose run --rm agent calibrate`; aggiorna `selectors.py` |
| Messaggio "Esito da verificare" (UNKNOWN) | inviato ma non verificabile | controlla su Cardmarket; in Operazioni: "Verificato: eseguita" oppure "Riprova" (verifica prima di reinviare) |
| Azioni sempre `NEEDS_ATTENTION` in live | selettori di scrittura non `verified` | comportamento voluto finché la calibrazione non è completata |
| Azioni ferme "In coda" | sessione non CONNECTED o backoff dopo errori | ripristina la connessione; controlla `not_before` e l'ultimo errore in Operazioni |
| Login: "Troppi tentativi" | rate limit | attendi `LOGIN_RATE_LIMIT_WINDOW_SECONDS` (default 5 min) |
| 403 "CSRF token non valido" | cookie `cmc_csrf` assente/scaduto | ricarica la pagina o rifai login |
| Login riuscito ma subito disconnesso su http | `COOKIE_SECURE=true` senza HTTPS | in locale imposta `COOKIE_SECURE=false` |
| Nessuna notifica push | VAPID mancanti, permesso negato, iPhone senza PWA installata | Impostazioni → Notifiche mostra la causa; su iOS aggiungi alla schermata Home |
| Dopo la cancellazione dati nessuna notifica | la prima sync è un *initial import* silenzioso | normale |
| API non parte in produzione | configurazione insicura | `docker compose -f docker-compose.prod.yml logs api`: token agent corto/segnaposto, password DB segnaposto, `SETUP_TOKEN` debole |
| `required variable ... is missing a value` | segreto mancante in `.env` (produzione) | imposta le voci `[PROD REQUIRED]` di `.env.example` |
| `/setup` dice "Setup via web disabilitato" | comportamento voluto in produzione | `docker compose -f docker-compose.prod.yml exec api python -m app.scripts.create_admin --email ...` |
| Chat senza template in produzione | `SEED_ON_START=false` | `docker compose -f docker-compose.prod.yml exec api python -m app.scripts.seed` (una volta) |
| agent `unhealthy` | loop bloccato o API irraggiungibile da > 5 min | `docker compose ... exec agent python -m agent healthcheck` per il motivo; `logs agent` |
| web `unhealthy` | API irraggiungibile dal container web | controlla `api`; `exec web wget -qO- http://127.0.0.1:3000/healthz` |
| Pairing: pagina nera / screenshot vuoti | display virtuale non pronto | l'entrypoint attende Xvfb; verifica con `run --rm --no-deps -e HEADLESS=false agent browser-selftest` |
| `Database non disponibile` (503) | PostgreSQL riavviato/giù | l'API si riconnette da sola (`pool_pre_ping`); controlla `docker compose logs postgres` |

## Log utili
```bash
docker compose logs -f agent | grep -E '"level": "(WARNING|ERROR)"'
docker compose logs api | grep <request_id|sync_id|action_id>
```
Un'azione si segue end-to-end con il suo `correlation_id` (= request id della richiesta utente) e `action_id`.

## Reset completo dell'ambiente di SVILUPPO (distrugge dati e sessione! mai in produzione)
```bash
docker compose down -v
```
