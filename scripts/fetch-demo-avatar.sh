#!/usr/bin/env bash
# Downloads the placeholder avatar (CC0, from the TalkingHead project) and
# shrinks its textures for the web: 37 MB -> about 18 MB, rig and all 66
# face blendshapes kept.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p avatars
tmp="$(mktemp -d)"
echo "==> Downloading the placeholder avatar"
curl -fL --progress-bar -o "$tmp/mpfb.glb" https://raw.githubusercontent.com/met4citizen/TalkingHead/main/avatars/mpfb.glb
echo "==> Compressing textures"
npx --yes @gltf-transform/cli@4 resize "$tmp/mpfb.glb" "$tmp/r.glb" --width 1024 --height 1024
npx --yes @gltf-transform/cli@4 webp "$tmp/r.glb" avatars/demo.glb
rm -rf "$tmp"
echo "==> avatars/demo.glb ready"
