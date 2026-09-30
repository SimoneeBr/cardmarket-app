#!/usr/bin/env bash
# Fails if the repository tracks (or would not ignore) files that must never be
# committed: dependencies, build output, secrets, browser profiles, real
# screenshots/traces/artifacts, local databases.
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0

# 1. Nothing forbidden is tracked (portable: no GNU-only grep flags).
tracked=$(git ls-files | python3 -c '
import re, sys
bad = re.compile(
    r"(^|/)(node_modules|\.venv|\.next|test-results|playwright-report|browser-profiles?|artifacts"
    r"|screenshots|traces|storage|data|backups|secrets|credentials)/"
    r"|\.egg-info/|\.tsbuildinfo$|(^|/)\.env$|(^|/)\.env\.(?!example$)"
    r"|\.trace\.zip$|\.(db|sqlite3?|dump|pem|key|p12|pfx|gpg)$"
)
print("\n".join(line for line in sys.stdin.read().splitlines() if bad.search(line)))
')
if [ -n "$tracked" ]; then
  echo "Forbidden files are tracked:"; echo "$tracked"; fail=1
fi

# 2. Images may only be the app icons or the anonymised test fixtures.
if imgs=$(git ls-files '*.png' '*.jpg' '*.jpeg' '*.webp' | grep -vE '^apps/web/public/icons/|^apps/agent/tests/fixtures/'); then
  echo "Unexpected images tracked (real screenshots?):"; echo "$imgs"; fail=1
fi

# 3. Sensitive paths are ignored by .gitignore.
for path in .env .env.production node_modules/x apps/web/app.tsbuildinfo apps/api/cmc_api.egg-info/PKG-INFO \
  data/browser-profile/Default/Cookies browser-profile/Default storage/x artifacts/shot.png \
  apps/agent/artifacts/x.png x.trace.zip tests/e2e/test-results/a tests/e2e/.auth/admin.json \
  backups/cmc-db.dump local.sqlite secrets/token credentials.json server.key; do
  git check-ignore -q "$path" || { echo "NOT ignored: $path"; fail=1; }
done

# 4. Useful project files are NOT ignored.
for path in .env.example "apps/web/src/app/(app)/settings/profile/page.tsx" apps/web/public/icons/icon-192.png \
  apps/agent/tests/fixtures/cardmarket/login.html packages/types/src/api.ts; do
  if git check-ignore -q "$path"; then echo "Wrongly ignored: $path"; fail=1; fi
done

# 5. No private keys / obvious secrets in tracked files.
if git grep -lE -e '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' -e 'AKIA[0-9A-Z]{16}' -- . ':!scripts/check-repo-hygiene.sh' >/dev/null; then
  echo "Private key / credential material found in tracked files"; fail=1
fi

[ "$fail" = 0 ] && echo "repository hygiene OK"
exit "$fail"
