# Cardmarket HTML fixtures

**These pages are NOT copies of real Cardmarket pages.** They reproduce the
structure the selector registry (`agent/cardmarket/selectors.py`) expects, so
the parsers, the session detector and the write-action guard can be tested
without a Cardmarket account and without hitting the real site.

When the registry is calibrated against the live site (`python -m agent
calibrate`), replace these files with *anonymised* captures of the real pages
(remove buyer names, addresses, messages) and update the tests.
