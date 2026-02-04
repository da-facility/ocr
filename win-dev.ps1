# Development server launcher for Windows
# Runs both backend and frontend in the same terminal using mise

param(
    [string]$ListenAddress = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

# Fix Unicode output (for Vite's fancy characters)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "Starting OCR Camera App (Development Mode)" -ForegroundColor Cyan
Write-Host ""

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Check if running from correct directory
if (-not (Test-Path "$scriptDir\backend\main.py")) {
    Write-Host "ERROR: Please run this script from the project root directory" -ForegroundColor Red
    exit 1
}

# Check if mise is available
if (-not (Get-Command mise -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: mise is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Install from: https://mise.jdx.dev" -ForegroundColor Yellow
    exit 1
}

# Install dependencies if not skipped
if (-not $SkipInstall) {
    Write-Host "Installing dependencies..." -ForegroundColor Gray

    if (-not $FrontendOnly) {
        Write-Host "  Backend (uv sync)..." -ForegroundColor Gray
        Push-Location "$scriptDir\backend"
        cmd /c "mise exec -- uv sync 2>nul"
        Pop-Location
    }

    if (-not $BackendOnly) {
        Write-Host "  Frontend (bun install)..." -ForegroundColor Gray
        Push-Location "$scriptDir\frontend"
        cmd /c "mise exec -- bun install 2>nul"
        Pop-Location
    }

    Write-Host ""
}

$jobs = @()

try {
    if (-not $FrontendOnly) {
        Write-Host "Starting backend server on ${ListenAddress}:${Port}..." -ForegroundColor Green
        $backendJob = Start-Job -Name "Backend" -ScriptBlock {
            param($dir, $h, $p)
            Set-Location "$dir\backend"
            mise exec -- uv run python main.py --host $h --port $p 2>&1
        } -ArgumentList $scriptDir, $ListenAddress, $Port
        $jobs += $backendJob
    }

    if (-not $BackendOnly) {
        # Wait a moment for backend to start
        Start-Sleep -Seconds 2
        Write-Host "Starting frontend dev server..." -ForegroundColor Green
        $frontendJob = Start-Job -Name "Frontend" -ScriptBlock {
            param($dir)
            Set-Location "$dir\frontend"
            mise exec -- bun run dev 2>&1
        } -ArgumentList $scriptDir
        $jobs += $frontendJob
    }

    Write-Host ""
    Write-Host "Servers running. Press Ctrl+C to stop." -ForegroundColor Gray
    Write-Host ""
    if (-not $FrontendOnly) {
        Write-Host "  Backend:  http://${ListenAddress}:${Port}" -ForegroundColor Yellow
    }
    if (-not $BackendOnly) {
        Write-Host "  Frontend: http://localhost:5173" -ForegroundColor Yellow
    }
    Write-Host ""

    # Stream output from both jobs
    while ($true) {
        foreach ($job in $jobs) {
            $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
            if ($output) {
                $prefix = if ($job.Name -eq "Backend") { "[BE]" } else { "[FE]" }
                $color = if ($job.Name -eq "Backend") { "Cyan" } else { "Magenta" }
                $output | ForEach-Object { Write-Host "$prefix $_" -ForegroundColor $color }
            }

            # Check if job failed
            if ($job.State -eq "Failed") {
                Write-Host "$($job.Name) server crashed!" -ForegroundColor Red
                Receive-Job -Job $job -ErrorAction SilentlyContinue | Write-Host -ForegroundColor Red
            }
        }
        Start-Sleep -Milliseconds 200
    }
}
finally {
    Write-Host ""
    Write-Host "Shutting down..." -ForegroundColor Yellow

    foreach ($job in $jobs) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Done." -ForegroundColor Green
}
