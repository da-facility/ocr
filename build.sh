#!/bin/bash
set -e
cd "$(dirname "$0")"

command -v uv &>/dev/null || { echo "ERROR: uv not installed"; exit 1; }
command -v bun &>/dev/null || { echo "ERROR: bun not installed"; exit 1; }

echo "[1/4] Installing backend dependencies..."
cd backend && uv sync && uv pip install pyinstaller

echo "[2/4] Installing frontend dependencies..."
cd ../frontend && bun install

echo "[3/4] Building frontend..."
bun run build

echo "[4/4] Building executable..."
cd ../backend && uv run pyinstaller ocr-camera.spec --noconfirm --clean --distpath ../dist

echo ""
echo "Built: dist/OCR-Camera"
