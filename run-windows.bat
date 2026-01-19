@echo off
echo Starting OCR Camera App (Development Mode)
echo.

:: Check if running from correct directory
if not exist "backend\main.py" (
    echo ERROR: Please run this script from the project root directory
    pause
    exit /b 1
)

:: Start backend
echo Starting backend server...
cd backend
start "OCR Backend" cmd /c "python main.py --host 127.0.0.1 --port 8000"

:: Wait for backend to start
timeout /t 2 /nobreak >nul

:: Start frontend (dev mode)
echo Starting frontend dev server...
cd ..\frontend
start "OCR Frontend" cmd /c "bun run dev"

:: Wait and open browser
timeout /t 3 /nobreak >nul
start http://localhost:5173

echo.
echo Both servers are running in separate windows.
echo Close those windows to stop the servers.
echo.
pause
