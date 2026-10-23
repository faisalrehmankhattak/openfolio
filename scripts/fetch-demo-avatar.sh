#!/usr/bin/env bash
# Official male sample from readyplayerme/visage, pinned and checksum-verified.
# See avatars/README.md and avatars/LICENSE-readyplayerme.txt for attribution.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p avatars
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fL --retry 3 -o "$tmp/male.glb" \
  https://raw.githubusercontent.com/readyplayerme/visage/0eafdd9c4c10db079de2656c3eb59212a2fb7f63/public/male.glb
expected=b06bd9df4d7d71d92774f895be31305cb8ff26f966f4c353beb82d3ccd94bea2
if command -v sha256sum >/dev/null; then
  actual="$(sha256sum "$tmp/male.glb" | cut -d ' ' -f 1)"
else
  actual="$(shasum -a 256 "$tmp/male.glb" | cut -d ' ' -f 1)"
fi
[ "$actual" = "$expected" ] || { echo "Avatar checksum mismatch" >&2; exit 1; }
cp "$tmp/male.glb" avatars/demo.glb
echo "Male demo avatar ready"
