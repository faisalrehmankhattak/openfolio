#!/usr/bin/env bash
# One command to run Openfolio locally: install, build the widget, start the server.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "Install uv first: https://docs.astral.sh/uv/"; exit 1; }
command -v npm >/dev/null || { echo "Install Node.js 18+ first: https://nodejs.org"; exit 1; }
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example. Add your keys, then run this again."; exit 1; }

echo "==> Building the widget"
(cd embed && npm install --no-audit --no-fund && npm run build)

echo "==> Installing the voice worker"
(cd worker && uv sync)

[ -f avatars/demo.glb ] || ./scripts/fetch-demo-avatar.sh

echo "==> Starting on http://127.0.0.1:7860"
cd worker && exec uv run openfolio-worker --host 127.0.0.1 --port 7860
