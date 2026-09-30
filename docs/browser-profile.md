# Il browser profile è una credenziale

`/data/browser-profile` (volume `…_browser-profile`) contiene il profilo Chromium dell'agent, **inclusi i cookie della sessione Cardmarket autenticata**. Chi ha una copia del profilo può, finché la sessione è valida, agire sull'account Cardmarket del negozio **senza password né 2FA**. Trattalo come una password in chiaro.

## Accesso amministrativo

- Solo chi ha accesso root o al gruppo `docker` sul server può leggere il volume: limita questi accessi alle persone che amministrano il negozio.
- Il profilo è montato solo nel container `agent` (utente `pwuser`, directory `0700`). API, web e Caddy non lo vedono.
- Il viewer noVNC (pairing) è disattivato di default, protetto da `PAIRING_VNC_PASSWORD` e pubblicato solo su `127.0.0.1`: si raggiunge con `ssh -L 6080:localhost:6080 utente@server`. Disattivalo (`PAIRING_VNC_ENABLED=false`) quando il pairing è finito.
- Non usare `docker cp` o shell interattive per copiare il profilo altrove: usa lo script qui sotto (backup sempre cifrati).

## Cosa NON deve mai contenerlo

- Repository Git (è escluso da `.gitignore`; `scripts/check-repo-hygiene.sh` lo verifica anche in CI).
- CI/CD: nessuna pipeline ne ha bisogno; nessun job usa credenziali Cardmarket.
- Immagini Docker (è solo un volume; `.dockerignore` esclude `data/`).
- Backup applicativi normali del database (`scripts/backup-db.sh` non lo include) e backup "a caldo" dell'intero server non cifrati.
- Ticket, chat, email, allegati di supporto. Anche gli screenshot di errore (`agent-artifacts`) possono contenere dati dei clienti: non condividerli senza anonimizzarli.

## Backup (facoltativo, cifrato, separato)

Serve solo a evitare un nuovo pairing dopo la perdita del server. In alternativa basta rifare il pairing.

```bash
./scripts/browser-profile.sh backup /percorso/sicuro          # chiede la passphrase (gpg AES-256)
PROFILE_PASSPHRASE_FILE=/root/.cmc-profile-pass ./scripts/browser-profile.sh backup /percorso/sicuro   # non interattivo
```
Lo script ferma l'agent (Chromium blocca il profilo), crea `browser-profile-<data>.tgz.gpg` (permessi 600) e riavvia l'agent. Conserva file e passphrase in posti diversi. Un backup non ha valore dopo che la sessione è scaduta o è stata revocata: non tenerne più di uno o due.

## Restore

```bash
./scripts/browser-profile.sh restore /percorso/sicuro/browser-profile-<data>.tgz.gpg --yes
```
Poi *Impostazioni → Connessione Cardmarket → Riconnetti* (verifica la sessione senza nuovo login). Se Cardmarket chiede di nuovo il login, esegui il re-pairing.

## Revoca / distruzione della sessione

Quando: dispositivo/server compromesso, backup del profilo perso, uscita di un amministratore, dismissione del server.

1. **Locale**: `./scripts/browser-profile.sh destroy --yes` — svuota il volume; l'agent riporterà `AUTH_REQUIRED` e nessuna azione verrà eseguita.
   Per eliminare anche il volume: `docker compose -f docker-compose.prod.yml stop agent && docker volume rm cardmarket-companion-prod_browser-profile`.
2. **Su Cardmarket** (indispensabile se una copia potrebbe essere in mani altrui): accedi all'account da un browser fidato e cambia la password e/o termina le sessioni attive dalle impostazioni di sicurezza dell'account, se disponibili. *TODO: VERIFY AGAINST LIVE CARDMARKET — il percorso esatto delle impostazioni di sicurezza non è stato verificato.*
3. Elimina i backup cifrati del profilo ormai inutili.
4. Registra l'evento (l'audit log dell'app registra le operazioni fatte da UI, non quelle fatte da shell).

## Re-pairing

1. `PAIRING_VNC_ENABLED=true` in `.env` → `docker compose -f docker-compose.prod.yml up -d agent`.
2. Tunnel: `ssh -L 6080:localhost:6080 utente@server`, apri `http://localhost:6080/vnc.html` (password `PAIRING_VNC_PASSWORD`).
3. App → *Impostazioni → Connessione Cardmarket → Avvia collegamento*.
4. Nel viewer fai **tu** login ed eventuale 2FA/CAPTCHA (l'agent non li automatizza mai).
5. Stato `CONNECTED` → rimetti `PAIRING_VNC_ENABLED=false` e `up -d agent`.
