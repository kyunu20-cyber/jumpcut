#!/usr/bin/env bash
# JUMPCUT.app과 설치용 dmg 만들기(Apple Silicon 전용). 결과: dist/JUMPCUT-<버전>-arm64.dmg
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
ARCH="$(uname -m)"
[ "$ARCH" = arm64 ] || { echo "Apple Silicon 맥에서만 빌드합니다." >&2; exit 1; }
VERSION="$("$PY" -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"

[ -f packaging/JUMPCUT.icns ] || "$PY" packaging/make_icon.py
"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/jumpcut.spec

# 끌어다 놓기 설치용 dmg (앱 + 응용 프로그램 폴더 바로가기)
STAGE="$(mktemp -d)"
cp -R dist/JUMPCUT.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="dist/JUMPCUT-$VERSION-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "JUMPCUT" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "$DMG"
