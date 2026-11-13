@echo off
cd /d "%~dp0"
if exist "results\pilot-report\index.html" (
  start "" "%~dp0results\pilot-report\index.html"
) else (
  echo Run RUN_HERE.ps1 -Mode Report first.
  pause
)
