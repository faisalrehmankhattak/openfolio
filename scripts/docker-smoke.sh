#!/usr/bin/env bash
# Validate the image without .env, provider keys, or paid requests.
set -euo pipefail
cd "$(dirname "$0")/.."
image="${1:-openfolio:local}"
docker run --rm --entrypoint /app/worker/.venv/bin/python \
  -e OPENFOLIO_SKIP_CHECKS=1 -e LLM_MODEL= -e LLM_API_KEY= \
  "$image" -c '
from pathlib import Path
from fastapi.testclient import TestClient
from openfolio_worker.config import ROOT, load_settings
from openfolio_worker.server import create_app
assert ROOT == Path("/app"), ROOT
s = load_settings()
assert s.personas_dir == Path("/app/personas")
assert s.inbox_dir == Path("/app/data/inbox")
with TestClient(create_app(s)) as client:
    for url in ("/", "/embed/embed.js", "/embed/app.js", "/avatars/demo.glb", "/v1/personas/faisal", "/livez"):
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)
    # Without provider keys the server must refuse calls up front, before WebRTC starts.
    ice = client.get("/v1/personas/faisal/ice-servers", headers={"origin": "http://localhost:7860"})
    assert ice.status_code == 503 and "not configured" in ice.text, (ice.status_code, ice.text)
    assert client.get("/healthz").status_code == 503
Path("/app/data/inbox/.smoke").write_text("ok")
Path("/app/data/inbox/.smoke").unlink()
print("PASS: installed package, demo, widget, avatar, persona, ICE, readiness, and writable inbox")
'
