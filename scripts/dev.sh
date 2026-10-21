#!/usr/bin/env bash
# One command to run Openfolio locally: install, build the widget, start the server.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "Install uv first: https://docs.astral.sh/uv/"; exit 1; }
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example. Add your keys, then run this again."; exit 1; }

# The widget build (Vite 8) needs Node 22.12+. A prebuilt widget in embed/dist
# is used as-is when Node is older, so the server still runs.
node_ok=0
command -v node >/dev/null && node_ok=$(node -e 'const [a,b]=process.versions.node.split(".").map(Number);console.log(a>22||(a===22&&b>=12)?1:0)')
if [ "$node_ok" = "1" ]; then
  echo "==> Building the widget"
  (cd embed && npm install --no-audit --no-fund && npm run build)
elif [ -f embed/dist/embed.js ]; then
  echo "==> Node 22.12+ not found; using the prebuilt widget in embed/dist"
else
  echo "Building the widget needs Node 22.12+. Install it with 'brew install node@22' or 'nvm install 22'."
  exit 1
fi

echo "==> Installing the voice worker"
(cd worker && uv sync)

[ -f avatars/demo.glb ] || ./scripts/fetch-demo-avatar.sh

echo "==> Starting on http://127.0.0.1:7860"
cd worker && exec uv run openfolio-worker --host 127.0.0.1 --port 7860
