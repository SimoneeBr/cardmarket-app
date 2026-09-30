# Cardmarket HTML fixtures

**These pages are NOT copies of real Cardmarket pages.** They reproduce the
structure the selector registry (`agent/cardmarket/selectors.py`) expects, so
the parsers, the session detector and the write-action guard can be tested
without a Cardmarket account and without hitting the real site.

**Exception:** `cloudflare_blocked.html` is a real capture of the Cloudflare
firewall page returned on 2026-09-30 (it is a Cloudflare page, not a Cardmarket
one and contains no Cardmarket data). The requester IP was replaced with the
documentation address `203.0.113.10`.

When the registry is calibrated against the live site (`python -m agent
calibrate`), replace these files with *anonymised* captures of the real pages
(remove buyer names, addresses, messages) and update the tests.
