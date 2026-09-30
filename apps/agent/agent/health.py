"""Application-level health of the agent (used by the container HEALTHCHECK).

The runner periodically writes a small JSON file with:
- ``loop_at``: the event loop is alive (not hung);
- ``api_ok_at``: last successful call to the companion API.

``python -m agent healthcheck`` exits 0 only if both are recent. A live
process that is stuck, or cannot talk to the API, is reported unhealthy.
"""

import json
import os
import time
from pathlib import Path

LOOP_STALE_SECONDS = 60
API_STALE_SECONDS = 300


def write_health(path: Path, api_ok_at: float | None, status: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"loop_at": time.time(), "api_ok_at": api_ok_at, "status": status}))
    os.replace(tmp, path)


def check_health(path: Path, now: float | None = None) -> tuple[bool, str]:
    now = now or time.time()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False, "no health file yet"
    loop_age = now - float(data.get("loop_at") or 0)
    api_at = data.get("api_ok_at")
    if loop_age > LOOP_STALE_SECONDS:
        return False, f"agent loop stalled ({loop_age:.0f}s)"
    if api_at is None or now - float(api_at) > API_STALE_SECONDS:
        return False, "no successful API contact recently"
    return True, f"ok (cardmarket session: {data.get('status')})"
