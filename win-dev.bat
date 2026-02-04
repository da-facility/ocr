@echo off
REM Development server launcher for Windows
REM Runs both backend and frontend in the same terminal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0win-dev.ps1" %*
