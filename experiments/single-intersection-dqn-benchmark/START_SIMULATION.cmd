@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0VIEW_SIMULATION.ps1" %*
set "TASK_EXIT=%ERRORLEVEL%"
if not "%TASK_EXIT%"=="0" echo Startup failed. See results\runtime-check.json and the message above.
pause
exit /b %TASK_EXIT%
