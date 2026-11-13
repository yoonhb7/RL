@echo off
cd /d "%~dp0"
echo Running the short 9-model pilot. Completed jobs are skipped.
powershell -NoProfile -ExecutionPolicy Bypass -File ".\RUN_HERE.ps1" -Mode Pilot
pause
