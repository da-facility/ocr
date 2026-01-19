#!/bin/bash
set -e

echo "Starting OCR Camera App (Development Mode)"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if running from correct directory
if [ ! -f "backend/main.py" ]; then
    echo "ERROR: Please run this script from the project root directory"
    exit 1
fi

# Determine Python command
PYTHON=$(command -v python3 || command -v python)

# Parse arguments
HOST="127.0.0.1"
PORT="8000"
FRONTEND_ONLY=false
BACKEND_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --host)
            HOST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --frontend-only)
            FRONTEND_ONLY=true
            shift
            ;;
        --backend-only)
            BACKEND_ONLY=true
            shift
            ;;
        --help)
            echo "Usage: ./run.sh [options]"
            echo ""
            echo "Options:"
            echo "  --host HOST       Backend host (default: 127.0.0.1)"
            echo "  --port PORT       Backend port (default: 8000)"
            echo "  --backend-only    Only start backend"
            echo "  --frontend-only   Only start frontend"
            echo "  --help            Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

cleanup() {
    echo ""
    echo "Shutting down..."
    kill $(jobs -p) 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

if [ "$FRONTEND_ONLY" = false ]; then
    echo "Starting backend server on $HOST:$PORT..."
    cd backend
    $PYTHON main.py --host "$HOST" --port "$PORT" &
    BACKEND_PID=$!
    cd ..
fi

if [ "$BACKEND_ONLY" = false ]; then
    sleep 1
    echo "Starting frontend dev server..."
    cd frontend
    npm run dev &
    FRONTEND_PID=$!
    cd ..
fi

echo ""
echo "Servers running. Press Ctrl+C to stop."
echo ""
if [ "$FRONTEND_ONLY" = false ]; then
    echo "  Backend:  http://$HOST:$PORT"
fi
if [ "$BACKEND_ONLY" = false ]; then
    echo "  Frontend: http://localhost:5173"
fi
echo ""

# Wait for processes
wait
