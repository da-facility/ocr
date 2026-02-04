#!/bin/bash
set -e
cd "$(dirname "$0")"

# Parse arguments
RELEASE_MODE=0
for arg in "$@"; do
    if [ "$arg" = "--release" ]; then
        RELEASE_MODE=1
    fi
done

command -v uv &>/dev/null || { echo "ERROR: uv not installed"; exit 1; }
command -v bun &>/dev/null || { echo "ERROR: bun not installed"; exit 1; }

if [ "$RELEASE_MODE" = "1" ]; then
    echo "Building RELEASE executable (smallest, UPX enabled, no sourcemaps)"
else
    echo "Building DEBUG executable (sourcemaps, no UPX, faster iterations)"
fi
echo ""

echo "[1/4] Installing backend dependencies..."
cd backend && uv sync

echo "[2/4] Installing frontend dependencies..."
cd ../frontend && bun install

echo "[3/4] Building frontend..."
if [ "$RELEASE_MODE" = "1" ]; then
    bun run build
else
    bun run build:debug
fi

echo "[4/4] Building executable..."
cd ../backend
if [ "$RELEASE_MODE" = "1" ]; then
    export RELEASE_BUILD=1
else
    export RELEASE_BUILD=0
fi
uv run pyinstaller ocr-camera.spec --noconfirm --distpath ../dist

echo ""
echo "Built: dist/OCR-Camera"
if [ "$RELEASE_MODE" = "0" ]; then
    echo "  (debug build with sourcemaps, no UPX)"
else
    echo "  (release build, UPX compressed)"
fi
