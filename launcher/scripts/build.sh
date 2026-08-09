#!/bin/bash
# build.sh — cross-build a Linux Electron AppDir (unpacked, no FUSE/AppImage
# needed) for the dpad-launcher, inside a node container (Docker Desktop is
# linux/x86_64). Output: dist/linux-unpacked/  (runnable: ./dpad-launcher).
#
# The host node_modules gets replaced with Linux deps during the build; we
# restore it for local previews afterward (so `npm start` still works on the
# dev box).
#
# Usage:  ./scripts/build.sh
set -euo pipefail
cd "$(dirname "$0")/.."   # launcher/

echo "[build] building Linux AppDir in node:20-bookworm (downloads linux electron)…"
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/work" -w /work node:20-bookworm bash -c "
  set -e
  npm install --no-audit --no-fund
  npx electron-builder --linux --dir
"

echo "[build] AppDir output:"
if [ -d dist/linux-unpacked ]; then
  ls -la dist/linux-unpacked/ | head
  echo "=== executable ==="; file dist/linux-unpacked/dpad-launcher 2>/dev/null || true
else
  echo "WARNING: dist/linux-unpacked not found; dist/ contents:"; ls -la dist/
fi

echo "[build] restoring host node_modules for local previews…"
npm install --no-audit --no-fund >/dev/null
echo "[build] done."