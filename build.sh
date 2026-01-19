#!/bin/bash
set -e

echo "========================================"
echo "  OCR Camera App - Build Script"
echo "========================================"
echo ""

# Determine OS
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]] || [[ -n "$WSL_DISTRO_NAME" ]]; then
    IS_WINDOWS=true
    echo "Platform: Windows/WSL"
else
    IS_WINDOWS=false
    echo "Platform: Unix/Mac"
fi

# Check Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "ERROR: Python is not installed"
    exit 1
fi
PYTHON=$(command -v python3 || command -v python)
echo "Python: $($PYTHON --version)"

# Check Bun
if ! command -v bun &> /dev/null; then
    echo "ERROR: Bun is not installed"
    echo "Install from https://bun.sh:"
    echo "  curl -fsSL https://bun.sh/install | bash"
    exit 1
fi
echo "Bun: $(bun --version)"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "[1/5] Installing backend dependencies..."
cd backend
$PYTHON -m pip install -e . --quiet
$PYTHON -m pip install pyinstaller --quiet

echo "[2/5] Installing frontend dependencies..."
cd ../frontend
bun install

echo "[3/5] Building frontend..."
bun run build

echo "[4/5] Building executable..."
cd ../backend

if [ "$IS_WINDOWS" = true ]; then
    # On Windows/WSL, use pyinstaller
    $PYTHON -m PyInstaller ocr-camera.spec --noconfirm
    
    echo ""
    echo "[5/5] Done!"
    echo ""
    echo "========================================"
    echo "  Build complete!"
    echo "  Executable: backend/dist/OCR-Camera.exe"
    echo "========================================"
else
    # On Unix/Mac, create a different output
    $PYTHON -m PyInstaller ocr-camera.spec --noconfirm
    
    echo ""
    echo "[5/5] Done!"
    echo ""
    echo "========================================"
    echo "  Build complete!"
    echo "  Executable: backend/dist/OCR-Camera"
    echo "========================================"
fi

echo ""
echo "Usage:"
echo "  ./OCR-Camera --host 0.0.0.0 --port 8080"
echo "  ./OCR-Camera --help"
