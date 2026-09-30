# Cardmarket agent

L'agent è l'unico componente che parla con Cardmarket. Usa **Playwright + Chromium** con un **profilo persistente**, interagisce con il sito come un browser reale (navigazione + DOM) e **non usa le API ufficiali** né endpoint interni non documentati.

> ⚠️ **Stato dell'adapter reale.** Selettori, URL e testi degli stati non sono ancora stati verificati su una sessione Cardmarket reale: sono marcati `TODO: VERIFY AGAINST LIVE CARDMARKET`. Le letture falliscono in sicurezza (`CARDMARKET_CHANGED`) e **le scritture sono bloccate** finché i selettori critici non sono marcati `verified=True` (vedi "Calibrazione").

## Ciclo di lavoro

```
loop:
  heartbeat (ogni HEARTBEAT_SECONDS) → riceve intervallo/comandi (SYNC_NOW, DISCONNECT, simulazioni mock)
  azioni: claim → execute → verify → report   (una alla volta, max N per giro)
  sync (ogni SYNC_INTERVAL_SECONDS o su richiesta):
      verifica sessione → lease di sync → ordini → chat → carrelli → complete
  attesa ACTION_POLL_SECONDS
```
- API irraggiungibile: backoff esponenziale con jitter (max 5 min), mai crash.
- Sync fallito: backoff esponenziale sul prossimo ciclo; notifica solo al primo errore di una serie.
- `SIGTERM`: termina l'azione corrente, chiude il browser (flush dei cookie nel profilo).

## Adapter

| Adapter | Quando | File |
|---|---|---|
| `MockCardmarketAdapter` | `MOCK_CARDMARKET=true` | `agent/mock/` — 24 ordini, 12 chat, 12 carrelli, stato su file, evoluzione casuale |
| `PlaywrightCardmarketAdapter` | `MOCK_CARDMARKET=false` | `agent/cardmarket/` |

Struttura `agent/cardmarket/`: `selectors.py` (registro unico), `urls.py`, `browser/` (contesto persistente, artifact), `auth/` (rilevamento sessione, pairing), `orders/`, `messages/`, `carts/` (reader), `parsers/` (HTML → modelli normalizzati, puri), `actions/` (guardia + scritture), `calibrate.py`.

Hook di test del mock nel testo del messaggio: `[mock:fail]` (errore di rete prima dell'invio → retry), `[mock:unverified]` (esito non verificabile → UNKNOWN), `[mock:unsafe]` (UI non riconosciuta → NEEDS_ATTENTION).

## Pairing (collegamento manuale)

1. Admin → *Impostazioni → Connessione Cardmarket → Avvia collegamento*. L'API accoda `PAIR_SESSION` e mette lo stato a `CONNECTING`.
2. L'agent riavvia Chromium **in modalità visibile** (display virtuale Xvfb nel container) e apre la pagina di login.
3. **Un umano** esegue il login e l'eventuale 2FA/CAPTCHA tramite il viewer noVNC:
   - abilita `PAIRING_VNC_ENABLED=true` e imposta `PAIRING_VNC_PASSWORD`;
   - la porta 6080 è pubblicata solo su `127.0.0.1`; da remoto: `ssh -L 6080:localhost:6080 server`, poi `http://localhost:6080/vnc.html`.
4. L'agent controlla la pagina ogni 3 s (timeout `PAIRING_TIMEOUT_SECONDS`, default 10 min). Rilevato il login, ricontrolla su una pagina normale, torna headless e riporta `CONNECTED`.

L'agent non digita mai credenziali, non conserva password o codici 2FA e non tenta di aggirare CAPTCHA/2FA.

In alternativa, pairing su un desktop: `MOCK_CARDMARKET=false BROWSER_PROFILE_DIR=./profile python -m agent pair`, poi cifra la cartella e ripristinala con `scripts/browser-profile.sh restore` (vedi [browser-profile.md](browser-profile.md)); cancella la copia locale al termine.

## Sessione

- I cookie restano **solo** nel profilo Chromium (`/data/browser-profile`, permessi `0700`). Il DB contiene solo un riferimento (`cardmarket_session`) e le date di pairing/verifica.
- Ogni pagina caricata passa dal rilevatore di sessione: se compare il form di login, 2FA o una challenge → `SESSION_EXPIRED`/`AUTH_REQUIRED`, stop immediato, screenshot, notifica agli admin.
- Le azioni di scrittura restano in coda (non vengono tentate) finché la sessione non torna `CONNECTED`.
- **Riconnetti** (`VERIFY_SESSION`) ricontrolla il profilo senza nuovo login; se non basta, **Avvia collegamento**.

## Accesso bloccato da un firewall (`ACCESS_BLOCKED`)

Se una pagina è il blocco del firewall di Cloudflare ("Sorry, you have been blocked"), Cardmarket non è stato raggiunto e lo stato della sessione è **sconosciuto**. Il detector restituisce `ERROR` / `ACCESS_BLOCKED` con il Ray ID nel messaggio (mai l'IP).

- L'agent **sospende ogni navigazione automatica**: niente sync programmati né `SYNC_NOW`, niente controllo della sessione all'avvio, nessuna azione di scrittura. Un blocco durante un sync interrompe subito il ciclo; un'azione colpita dal blocco non viene eseguita e resta in coda. Il pairing si interrompe subito.
- Lo stato è salvato dall'API (connessione `ERROR` + `last_error_code=ACCESS_BLOCKED`) e comunicato all'agent a ogni heartbeat (`access_blocked`), quindi **sopravvive ai riavvii** dell'agent. Gli admin ricevono una notifica una volta sola, all'inizio del blocco.
- Non esiste un retry automatico. **Resume**: solo con un'azione esplicita dell'operatore, cioè *Impostazioni → Connessione → Riconnetti* (`VERIFY_SESSION`: un solo controllo) o *Avvia collegamento*. Se la pagina risulta ancora bloccata, il blocco resta.
- Prima di riconnettere verifica l'accesso da un browser normale. Non si tenta mai di aggirare il firewall.



| Esito agent | Stato azione | Messaggio |
|---|---|---|
| eseguita **e** osservata su Cardmarket | `SUCCESS` | `SENT` |
| errore transitorio prima dell'invio | `PENDING` con backoff, poi `FAILED` | `PENDING` → `FAILED` |
| inviata ma non verificabile | `NEEDS_ATTENTION` | `UNKNOWN` |
| UI non riconosciuta/ambigua, selettori non verificati, entità sbagliata | `NEEDS_ATTENTION` | `FAILED` |

Regole di sicurezza implementate:
- prima di agire si riapre la pagina e si controlla che sia **la conversazione/l'ordine giusto** (id nella pagina, acquirente);
- ogni elemento critico deve risolversi a **esattamente un** elemento visibile e abilitato (`actions/guard.py`), mai "il primo che trovo";
- dopo il click finale nessuna eccezione è trattata come "non inviato" (eviterebbe il retry cieco);
- lease scaduto (crash) o esito incerto → `needs_verification`: al nuovo tentativo l'agent **cerca prima** il messaggio su Cardmarket (stesso testo, dopo `requested_at`) e lo rimanda solo se assente;
- il sync successivo riconcilia i messaggi `UNKNOWN` se li trova sulla pagina.

L'operatore può, da *Operazioni*: riprovare, annullare, o confermare "verificato: eseguita" dopo un controllo manuale.

## Errori e artifact

Classificazione: `AUTH_ERROR`, `NETWORK_ERROR`, `CARDMARKET_CHANGED`, `SELECTOR_NOT_FOUND`, `TIMEOUT`, `ACTION_FAILED`, `VERIFICATION_FAILED`, `DATABASE_ERROR`, `UNKNOWN`.
Su errore: screenshot a pagina intera in `/data/artifacts` (visibile dagli admin in *Operazioni*), trace Playwright se `TRACE_ON_FAILURE=true`, HTML se `DEBUG_CAPTURE_HTML=true` (solo sviluppo: contiene dati dei clienti). Si conservano gli ultimi `ARTIFACTS_KEEP` file.

## Calibrazione e aggiornamento dei selettori

1. Fai il pairing con un account reale.
2. `docker compose run --rm agent calibrate` (sola lettura: nessun click). Stampa, per ogni selettore del registro, quanti elementi matchano sulle pagine note e salva screenshot + HTML in `/data/artifacts`.
3. Aggiorna **solo** `agent/cardmarket/selectors.py` (e `urls.py`, mappe stato in `parsers/common.py`). Preferenza: ruolo/label/testo → data-attribute → CSS; XPath solo se inevitabile; niente `nth-child` o classi hashate.
4. Sostituisci le fixture in `apps/agent/tests/fixtures/cardmarket/` con catture **anonimizzate** e aggiorna i test.
5. Solo dopo aver verificato le pagine di scrittura su casi reali, imposta `verified=True` sui selettori `critical` e aggiorna `REGISTRY_VERSION`.

Se Cardmarket cambia il DOM, i parser alzano `CARDMARKET_CHANGED`: l'agent smette di agire su quella sezione, la dashboard mostra l'errore, e basta ripetere la calibrazione.

## Backup, revoca e re-pairing del profilo browser

Il profilo contiene la sessione autenticata ed è una **credenziale**: backup (sempre cifrato e separato dai backup del DB), restore, distruzione/revoca della sessione, re-pairing, chi può accedervi e dove non deve mai finire sono descritti in [browser-profile.md](browser-profile.md) e gestiti con `scripts/browser-profile.sh`.

## Verifiche senza contattare Cardmarket

- `docker compose -f docker-compose.prod.yml run --rm --no-deps agent browser-selftest` — avvia Chromium con il profilo reale sotto l'hardening del container e carica solo una pagina `data:` locale. Con l'agent in esecuzione su un profilo in uso, fermalo prima (Chromium blocca il profilo).
- `python -m agent healthcheck` — healthcheck del container (event loop vivo e contatto recente con l'API).
