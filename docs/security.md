# Sicurezza e privacy

## Credenziali Cardmarket
- Mai richieste dall'app, mai salvate nel DB, mai nei log. Il login è fatto da un umano durante il pairing.
- La sessione vive solo nel profilo Chromium su volume privato (`0700`). Il DB contiene solo un riferimento.
- 2FA e CAPTCHA non vengono mai automatizzati o aggirati.

## Autenticazione applicativa
- Password Argon2id (argon2-cffi), rehash automatico se cambiano i parametri, minimo 10 caratteri con lettere e numeri/simboli.
- Verifica password eseguita anche per email inesistenti (niente user enumeration via timing).
- Sessioni server-side: token casuale 256 bit, nel DB solo SHA-256; scadenza `SESSION_TTL_HOURS`; revoca a logout, cambio password, disattivazione utente.
- Cookie `HttpOnly`, `SameSite=Lax`, `Secure` in produzione.
- CSRF: double-submit (`cmc_csrf` + header `X-CSRF-Token`) su ogni richiesta mutante autenticata.
- Rate limiting: login (per IP e per email), setup iniziale, invio messaggi per utente.

## Autorizzazione (server-side)

| Permesso | STAFF | MANAGER | ADMIN |
|---|:-:|:-:|:-:|
| Vedere ordini/chat/carrelli, notifiche | ✓ | ✓ | ✓ |
| Inviare messaggi, segnare spedito | ✓ | ✓ | ✓ |
| Template, operazioni (coda, sync, audit), sync manuale, gestione azioni | | ✓ | ✓ |
| Pairing/connessione, utenti, impostazioni, simulazioni, cancellazione dati | | | ✓ |

Definito in `apps/api/app/security/permissions.py` e applicato con dipendenze FastAPI su ogni endpoint (testato in `tests/integration/test_auth.py`).

## Agent
- Endpoint `/internal/agent/*` protetti da bearer token (confronto a tempo costante), mai esposti dal proxy web né da Caddy.
- Il viewer noVNC per il pairing è disattivato di default, protetto da password e pubblicato solo su `127.0.0.1`.

## Log e audit
- Log JSON strutturati; chiavi sensibili (`password`, `token`, `cookie`, `authorization`, `body`...) sempre redatte; il testo dei messaggi non viene loggato.
- Audit log per: login/logout/falliti, setup, utenti, invio messaggi, spedizioni, esiti azioni, pairing/reconnect/disconnect, cambi stato sessione, sync falliti, impostazioni, template, simulazioni, cancellazione dati.

## Privacy
- Dati minimi: solo ciò che serve all'operatività (nessun indirizzo di spedizione viene estratto).
- Retention configurabile (`RETENTION_*`), applicata ogni ora e su richiesta; sessioni scadute eliminate.
- Admin → *Sistema e privacy*: cancellazione completa dei dati locali di Cardmarket (non tocca Cardmarket).
- Nessun analytics di terze parti. Il service worker non mette mai in cache le risposte `/api`.
- `DEBUG_CAPTURE_HTML` e le trace contengono dati dei clienti: solo per debug, retention limitata (`ARTIFACTS_KEEP`).

## Header e trasporto
HSTS (Caddy), `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `Cache-Control: no-store` sulle API.
