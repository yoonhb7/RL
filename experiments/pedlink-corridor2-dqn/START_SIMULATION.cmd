@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_HERE.ps1" -Mode View -Variant adaptive
if errorlevel 1 pause
