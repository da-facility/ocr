@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   OCR Camera App - Windows Build Script
echo ========================================
echo.

:: Get script directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.9+ from https://python.org
    pause
    exit /b 1
)

:: Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed or not in PATH
    echo Please install Node.js 18+ from https://nodejs.org
    pause
    exit /b 1
)

:: Check if spec file exists
if not exist "backend\ocr-camera.spec" (
    echo ERROR: ocr-camera.spec not found in backend folder
    echo Make sure you have the complete project files.
    pause
    exit /b 1
)

echo [1/5] Installing backend dependencies...
cd backend
pip install -e . --quiet
pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: Failed to install backend dependencies
    pause
    exit /b 1
)

echo [2/5] Installing frontend dependencies...
cd ..\frontend
call npm install --silent
if errorlevel 1 (
    echo ERROR: Failed to install frontend dependencies
    pause
    exit /b 1
)

echo [3/5] Building frontend...
call npm run build
if errorlevel 1 (
    echo ERROR: Failed to build frontend
    pause
    exit /b 1
)

echo [4/5] Building executable...
cd ..\backend
echo Using spec file: %CD%\ocr-camera.spec
pyinstaller "%CD%\ocr-camera.spec" --noconfirm
if errorlevel 1 (
    echo ERROR: Failed to build executable
    pause
    exit /b 1
)

echo [5/5] Done!
echo.
echo ========================================
echo   Build complete!
echo   Executable: %SCRIPT_DIR%backend\dist\OCR-Camera.exe
echo ========================================
echo.
echo Usage:
echo   OCR-Camera.exe --host 0.0.0.0 --port 8080
echo   OCR-Camera.exe --help
echo.

pause
