@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Parse arguments
set "RELEASE_MODE=0"
for %%a in (%*) do (
    if "%%a"=="--release" set "RELEASE_MODE=1"
)

where uv >nul 2>&1 || (echo ERROR: uv not installed & exit /b 1)
where bun >nul 2>&1 || (echo ERROR: bun not installed & exit /b 1)

if "%RELEASE_MODE%"=="1" (
    echo Building RELEASE executable (smallest, UPX enabled, no sourcemaps)
) else (
    echo Building DEBUG executable (sourcemaps, no UPX, faster iterations)
)
echo.

echo [1/4] Installing backend dependencies...
cd backend && uv sync
if errorlevel 1 exit /b 1

echo [2/4] Installing frontend dependencies...
cd ..\frontend && call bun install
if errorlevel 1 exit /b 1

echo [3/4] Building frontend...
if "%RELEASE_MODE%"=="1" (
    call bun run build
) else (
    call bun run build:debug
)
if errorlevel 1 exit /b 1

echo [4/4] Building executable...
cd ..\backend
if "%RELEASE_MODE%"=="1" (
    set "RELEASE_BUILD=1"
) else (
    set "RELEASE_BUILD=0"
)
uv run pyinstaller ocr-camera.spec --noconfirm --distpath ..\dist
if errorlevel 1 exit /b 1

echo.
echo Built: dist\OCR-Camera.exe
if "%RELEASE_MODE%"=="0" (
    echo   (debug build with sourcemaps, no UPX)
) else (
    echo   (release build, UPX compressed)
)
