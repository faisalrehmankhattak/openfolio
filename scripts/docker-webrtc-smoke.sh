#!/usr/bin/env bash
# Requires the development Python environment (cd worker && uv sync --group dev).
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -p openfolio-smoke -f compose.yaml -f compose.smoke.yaml)
trap '"${compose[@]}" down -v --remove-orphans >/dev/null' EXIT
"${compose[@]}" up -d --no-build
./worker/.venv/bin/python - <<'PYTHON'
import time
import urllib.request
for attempt in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:17862/livez", timeout=1)
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("Container did not start in 60 seconds")
PYTHON
./worker/.venv/bin/python scripts/rtc-smoke.py client
