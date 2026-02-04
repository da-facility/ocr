@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Defaults
set "RELEASE_MODE=0"
set "OUTPUT_NAME=OCR-Camera"
set "OUTPUT_DIR=dist"

:: Parse arguments
:parse_args
if "%~1"=="" goto done_args
if "%~1"=="--release" (
    set "RELEASE_MODE=1"
    shift
    goto parse_args
)
if "%~1"=="--output" (
    set "OUTPUT_NAME=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="--directory" (
    set "OUTPUT_DIR=%~2"
    shift
    shift
    goto parse_args
)
shift
goto parse_args
:done_args

where uv >nul 2>&1 || (echo ERROR: uv not installed & exit /b 1)
where bun >nul 2>&1 || (echo ERROR: bun not installed & exit /b 1)

if "%RELEASE_MODE%"=="1" (
    echo Building RELEASE executable (smallest, UPX enabled, no sourcemaps)
) else (
    echo Building DEBUG executable (sourcemaps, no UPX, faster iterations)
)
echo   Output: %OUTPUT_DIR%\%OUTPUT_NAME%.exe
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
set "OUTPUT_NAME=%OUTPUT_NAME%"
uv run pyinstaller ocr-camera.spec --noconfirm --distpath ..\%OUTPUT_DIR%
if errorlevel 1 exit /b 1

echo.
echo Built: %OUTPUT_DIR%\%OUTPUT_NAME%.exe
if "%RELEASE_MODE%"=="0" (
    echo   (debug build with sourcemaps, no UPX)
) else (
    echo   (release build, UPX compressed)
)
