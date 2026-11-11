@echo off
setlocal
cd /d "%~dp0"
set "DEMO_MODEL=models/corridor2-100ep/model.pt"
if exist "results\local\corridor2-train\model.pt" set "DEMO_MODEL=results/local/corridor2-train/model.pt"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN_HERE.ps1" -Mode View -Scenario corridor2 -Controller dqn -ModelPath "%DEMO_MODEL%" -OutputPath results/local/corridor2-demo -Delay 1000
if errorlevel 1 (
  echo.
  echo Simulation could not start. See the error above and sumo-startup.log.
  pause
)
endlocal
