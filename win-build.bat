@echo off
cd /d "%~dp0"

where uv >nul 2>&1 || (echo ERROR: uv not installed & exit /b 1)
where bun >nul 2>&1 || (echo ERROR: bun not installed & exit /b 1)

echo [1/4] Installing backend dependencies...
cd backend && uv sync && uv pip install pyinstaller
if errorlevel 1 exit /b 1

echo [2/4] Installing frontend dependencies...
cd ..\frontend && call bun install
if errorlevel 1 exit /b 1

echo [3/4] Building frontend...
call bun run build
if errorlevel 1 exit /b 1

echo [4/4] Building executable...
cd ..\backend && uv run pyinstaller ocr-camera.spec --noconfirm --clean --distpath ..\dist
if errorlevel 1 exit /b 1

echo.
echo Built: dist\OCR-Camera.exe
