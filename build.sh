#!/bin/bash
set -e
cd "$(dirname "$0")"

# Defaults
RELEASE_MODE=0
OUTPUT_NAME="OCR-Camera"
OUTPUT_DIR="dist"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --release)
            RELEASE_MODE=1
            shift
            ;;
        --output)
            OUTPUT_NAME="$2"
            shift 2
            ;;
        --directory)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

command -v uv &>/dev/null || { echo "ERROR: uv not installed"; exit 1; }
command -v bun &>/dev/null || { echo "ERROR: bun not installed"; exit 1; }

if [ "$RELEASE_MODE" = "1" ]; then
    echo "Building RELEASE executable (smallest, UPX enabled, no sourcemaps)"
else
    echo "Building DEBUG executable (sourcemaps, no UPX, faster iterations)"
fi
echo "  Output: $OUTPUT_DIR/$OUTPUT_NAME"
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
export OUTPUT_NAME
uv run pyinstaller ocr-camera.spec --noconfirm --distpath ../$OUTPUT_DIR

echo ""
echo "Built: $OUTPUT_DIR/$OUTPUT_NAME"
if [ "$RELEASE_MODE" = "0" ]; then
    echo "  (debug build with sourcemaps, no UPX)"
else
    echo "  (release build, UPX compressed)"
fi
