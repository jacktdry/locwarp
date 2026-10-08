#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
export PYINSTALLER_CONFIG_DIR="$ROOT/build-py/pyinstaller-cache"
[[ "$(uname -s)" == Darwin ]] || { echo 'Build on macOS, not by cross-compiling.' >&2; exit 1; }
PYTHON="${LOCWARP_PYTHON:-python3.13}"
ARCH="$("$PYTHON" -c 'import platform, sys; assert sys.version_info[:2] == (3, 13), "Python 3.13 required"; print({"arm64":"arm64", "x86_64":"x64"}[platform.machine()])')"
[[ "${1:-$ARCH}" == "$ARCH" ]] || { echo "Python architecture is $ARCH; use a matching host/Python for ${1}." >&2; exit 1; }
# Separate from the developer/orchestrator venv; never run this concurrently.
VENV="$ROOT/.venv-macos-$ARCH"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install -r backend/requirements.txt 'pyinstaller>=6.19,<7'
(cd backend && "$VENV/bin/python" -m unittest discover -s tests -v)
"$VENV/bin/python" -m PyInstaller backend/locwarp-backend.spec --noconfirm \
  --distpath "$ROOT/dist-py/mac-$ARCH" --workpath "$ROOT/build-py/mac-$ARCH"
"$ROOT/dist-py/mac-$ARCH/locwarp-backend/locwarp-backend" --self-test
# Preserve the original artwork. Generate a macOS icon using Apple's tools.
ICONSET="$ROOT/build-py/LocWarp.iconset"
mkdir -p "$ICONSET"
for SIZE in 16 32 128 256 512; do
  sips -z "$SIZE" "$SIZE" frontend/build/icon.png --out "$ICONSET/icon_${SIZE}x${SIZE}.png" >/dev/null
  DOUBLE=$((SIZE * 2))
  sips -z "$DOUBLE" "$DOUBLE" frontend/build/icon.png --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o frontend/build/icon.icns
cd frontend
# npm ci is intentionally separate; do not mutate an ongoing installation.
npm test
npm run build
if [[ "${LOCWARP_MAC_DIR_ONLY:-0}" == 1 ]]; then
  npx --no-install electron-builder --mac --dir "--$ARCH" --publish never
else
  npm run dist:mac -- "--$ARCH"
fi
